from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import get_logger

from .content_generator import generate_post_from_messages, generate_post_from_topic
from .publish_command import _load_posts, _save_posts, _safe_int, _publish_remote

logger = get_logger("blog_publish_scheduler")


class BlogPublishScheduler:
    """
    定时发布调度器
    支持多任务配置：
    - 每日总结 (summary)
    - 话题生成 (topic)
    - 队列消费 (queue)
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.logger = get_logger("BlogPublishScheduler")
        self.status_path = "bot_side_plugin/data/schedule_status.json"

    def _get_timezone_now(self) -> datetime.datetime:
        timezone_str = self.plugin.get_config("schedule.timezone", "Asia/Shanghai")
        try:
            import pytz

            tz = pytz.timezone(timezone_str)
            return datetime.datetime.now(tz)
        except ImportError:
            self.logger.error("pytz 未安装，使用系统时间")
            return datetime.datetime.now()
        except Exception as exc:
            self.logger.error(f"时区处理失败: {exc}，使用系统时间")
            return datetime.datetime.now()

    def _normalize_path(self, path_value: str) -> str:
        return (path_value or "").replace("\\", "/")

    def _load_status(self) -> Dict[str, str]:
        """加载任务执行状态 {task_id: last_execution_date_str}"""
        path = self._normalize_path(self.status_path)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_status(self, status: Dict[str, str]) -> None:
        """保存任务执行状态"""
        path = self._normalize_path(self.status_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    def _generate_task_id(self, task: Dict[str, Any]) -> str:
        """生成任务唯一标识"""
        # 组合 type, time, topic 生成 hash
        raw = f"{task.get('type')}-{task.get('time')}-{task.get('topic', '')}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _get_tasks(self) -> List[Dict[str, Any]]:
        """获取配置的任务列表，兼容旧版配置"""
        tasks = self.plugin.get_config("schedule.tasks")
        if tasks and isinstance(tasks, list):
            return tasks
        
        # 兼容旧版单任务配置
        schedule_time = self.plugin.get_config("schedule.schedule_time")
        if schedule_time:
            return [{
                "time": schedule_time,
                "type": "queue"  # 旧版逻辑默认为消费队列
            }]
        return []

    async def start(self) -> None:
        if self.is_running:
            return

        enabled = bool(self.plugin.get_config("schedule.enabled", False))
        if not enabled:
            self.logger.info("定时发布已禁用")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._schedule_loop())
        self.logger.info("定时发布调度器已启动")

    async def stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.logger.info("定时发布调度器已停止")

    async def _schedule_loop(self) -> None:
        """主调度循环：每分钟检查一次任务"""
        while self.is_running:
            try:
                now = self._get_timezone_now()
                current_date_str = now.strftime("%Y-%m-%d")
                current_time_str = now.strftime("%H:%M")
                
                tasks = self._get_tasks()
                status = self._load_status()
                status_changed = False

                for task in tasks:
                    task_time = task.get("time")
                    if not task_time:
                        continue

                    task_id = self._generate_task_id(task)
                    last_run_date = status.get(task_id)

                    # 检查是否今天已经执行过
                    if last_run_date == current_date_str:
                        continue

                    # 检查是否到达或错过时间 (当前时间 >= 任务时间)
                    # 简单的字符串比较 "08:30" >= "08:00" 是有效的
                    if current_time_str >= task_time:
                        self.logger.info(f"触发定时任务: {task.get('type')} at {task_time}")
                        try:
                            await self._execute_task(task)
                            status[task_id] = current_date_str
                            status_changed = True
                        except Exception as e:
                            self.logger.error(f"任务执行失败: {e}")

                if status_changed:
                    self._save_status(status)

                # 等待到下一分钟的开始，避免重复执行
                # 或者简单 sleep 60秒。为了响应及时，sleep 30秒检测一次即可
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"调度循环出错: {exc}")
                await asyncio.sleep(60)

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_type = task.get("type")
        
        if task_type == "queue":
            await self._process_queue_task()
        elif task_type == "summary":
            await self._process_summary_task()
        elif task_type == "topic":
            topic = task.get("topic")
            if topic:
                await self._process_topic_task(topic)
            else:
                self.logger.warning("话题任务缺少 topic 参数，跳过")
        else:
            self.logger.warning(f"未知的任务类型: {task_type}")

    async def _publish_content(self, title: str, content: str) -> bool:
        """统一发布逻辑：优先远程 API，失败则本地保存"""
        api_url = self.plugin.get_config("blog_api.url", "")
        admin_password = self.plugin.get_config("blog_api.admin_password", "")
        timeout_seconds = int(self.plugin.get_config("blog_api.timeout_seconds", 10))
        posts_path = self._normalize_path(
            self.plugin.get_config("publish.posts_json_path", "blog_side_api/data/posts.json")
        )

        # 尝试远程发布
        if api_url:
            try:
                remote_id = await _publish_remote(api_url, admin_password, title, content, timeout_seconds)
                if remote_id:
                    self.logger.info(f"发布成功（远程）: {title} (ID={remote_id})")
                    return True
            except Exception as e:
                self.logger.error(f"远程发布失败: {e}，尝试本地保存")

        # 降级到本地保存
        try:
            posts = _load_posts(posts_path)
            max_id = max([_safe_int(str(x.get("id", 0))) for x in posts], default=0)
            new_id = max_id + 1
            created_at = self._get_timezone_now().isoformat(timespec="seconds")
            new_post = {
                "id": new_id,
                "title": title,
                "summary": content[:120] + ("..." if len(content) > 120 else ""),
                "content": content,
                "created_at": created_at,
            }
            posts.append(new_post)
            _save_posts(posts_path, posts)
            self.logger.info(f"发布成功（本地）: {title} (ID={new_id})")
            return True
        except Exception as e:
            self.logger.error(f"本地保存失败: {e}")
            return False

    async def _process_summary_task(self) -> None:
        """处理每日总结任务"""
        self.logger.info("开始生成每日总结...")
        result = await generate_post_from_messages(self.plugin.config or {})
        if result:
            title, content = result
            await self._publish_content(title, content)
        else:
            self.logger.info("每日总结生成未返回内容（可能消息不足）")

    async def _process_topic_task(self, topic: str) -> None:
        """处理话题生成任务"""
        self.logger.info(f"开始生成话题博客: {topic}")
        result = await generate_post_from_topic(topic, self.plugin.config or {})
        if result:
            title, content = result
            await self._publish_content(title, content)
        else:
            self.logger.error("话题博客生成失败")

    async def _process_queue_task(self) -> None:
        """处理队列任务（兼容旧逻辑）"""
        queue_path = self._normalize_path(
            self.plugin.get_config(
                "schedule.queue_json_path",
                "bot_side_plugin/data/scheduled_posts.json",
            )
        )
        max_posts = int(self.plugin.get_config("schedule.max_posts_per_run", 1))
        max_posts = max(1, max_posts)

        queue = self._load_queue(queue_path)
        if not queue:
            self.logger.info("定时队列为空")
            return

        now = self._get_timezone_now()
        published_count = 0
        remaining: List[Dict[str, Any]] = []

        for item in queue:
            if published_count >= max_posts:
                remaining.append(item)
                continue
            
            # 检查单条目的 publish_at (如果有)
            if not self._is_item_due(item, now):
                remaining.append(item)
                continue

            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            
            # 如果队列项没有内容，尝试自动生成（旧逻辑保留）
            if not title or not content:
                generated = await generate_post_from_messages(self.plugin.config or {})
                if generated:
                    title, content = generated
                else:
                    self.logger.error("队列条目无效且生成失败，跳过")
                    continue

            if await self._publish_content(title, content):
                published_count += 1
            else:
                # 发布失败，保留在队列中？或者丢弃？
                # 这里选择保留，以便重试
                remaining.append(item)

        if len(remaining) != len(queue):
            self._save_queue(queue_path, remaining)

    # --- 辅助方法 (保留旧版部分逻辑) ---

    def _load_queue(self, queue_path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(queue_path):
            return []
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as exc:
            self.logger.error(f"读取定时队列失败: {exc}")
            return []

    def _save_queue(self, queue_path: str, items: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    def _parse_publish_at(self, value: str) -> Optional[datetime.datetime]:
        if not value:
            return None
        try:
            dt = datetime.datetime.fromisoformat(value)
        except Exception:
            return None
        if dt.tzinfo is not None:
            return dt
        timezone_str = self.plugin.get_config("schedule.timezone", "Asia/Shanghai")
        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            return tz.localize(dt)
        except Exception:
            return dt

    def _is_item_due(self, item: Dict[str, Any], now: datetime.datetime) -> bool:
        publish_at = item.get("publish_at")
        if not publish_at:
            return True
        parsed = self._parse_publish_at(str(publish_at))
        if not parsed:
            return True
        return parsed <= now
