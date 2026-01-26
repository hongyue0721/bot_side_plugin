from __future__ import annotations

import asyncio
import datetime
import json
import os
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

from .publish_command import _load_posts, _save_posts, _safe_int, _publish_remote

logger = get_logger("blog_publish_scheduler")


class BlogPublishScheduler:
    """定时发布调度器（参考 diary_plugin 的调度逻辑）"""

    def __init__(self, plugin):
        self.plugin = plugin
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.logger = get_logger("BlogPublishScheduler")

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

    async def start(self) -> None:
        if self.is_running:
            return

        enabled = bool(self.plugin.get_config("schedule.enabled", False))
        if not enabled:
            self.logger.info("定时发布已禁用")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._schedule_loop())
        schedule_time = self.plugin.get_config("schedule.schedule_time", "23:30")
        self.logger.info(f"定时发布已启动，执行时间: {schedule_time}")

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
        self.logger.info("定时发布已停止")

    async def _schedule_loop(self) -> None:
        while self.is_running:
            try:
                now = self._get_timezone_now()
                schedule_time_str = self.plugin.get_config("schedule.schedule_time", "23:30")
                schedule_hour, schedule_minute = map(int, schedule_time_str.split(":"))
                today_schedule = now.replace(
                    hour=schedule_hour,
                    minute=schedule_minute,
                    second=0,
                    microsecond=0,
                )
                if now >= today_schedule:
                    today_schedule += datetime.timedelta(days=1)
                wait_seconds = (today_schedule - now).total_seconds()
                self.logger.info(
                    f"下次定时发布: {today_schedule.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await asyncio.sleep(wait_seconds)
                if self.is_running:
                    await self._publish_scheduled_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"定时任务出错: {exc}")
                await asyncio.sleep(60)

    async def _publish_scheduled_once(self) -> None:
        queue_path = self._normalize_path(
            self.plugin.get_config(
                "schedule.queue_json_path",
                "bot_side_plugin/data/scheduled_posts.json",
            )
        )
        posts_path = self._normalize_path(
            self.plugin.get_config("publish.posts_json_path", "blog_side_api/data/posts.json")
        )
        api_url = self.plugin.get_config("blog_api.url", "")
        admin_password = self.plugin.get_config("blog_api.admin_password", "")
        timeout_seconds = int(self.plugin.get_config("blog_api.timeout_seconds", 10))
        max_posts = int(self.plugin.get_config("schedule.max_posts_per_run", 1))
        max_posts = max(1, max_posts)

        queue = self._load_queue(queue_path)
        if not queue:
            self.logger.info("定时队列为空，无可发布内容")
            return

        now = self._get_timezone_now()
        published = 0
        remaining: List[Dict[str, Any]] = []

        for item in queue:
            if published >= max_posts:
                remaining.append(item)
                continue
            if not self._is_item_due(item, now):
                remaining.append(item)
                continue

            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            author = str(item.get("author", "MaiBot")).strip() or "MaiBot"
            if not title or not content:
                self.logger.error("定时队列条目缺少标题或正文，已跳过")
                continue

            remote_id = await _publish_remote(api_url, admin_password, title, content, author, timeout_seconds)
            if remote_id:
                published += 1
                self.logger.info(f"定时发布成功（远程）: {title} (ID={remote_id})")
                continue

            posts = _load_posts(posts_path)
            max_id = max([_safe_int(str(x.get("id", 0))) for x in posts], default=0)
            new_id = max_id + 1
            created_at = now.isoformat(timespec="seconds")
            new_post = {
                "id": new_id,
                "title": title,
                "summary": content[:120] + ("..." if len(content) > 120 else ""),
                "content": content,
                "author": author,
                "created_at": created_at,
            }
            posts.append(new_post)
            _save_posts(posts_path, posts)
            published += 1
            self.logger.info(f"定时发布成功（本地）: {title} (ID={new_id})")

        if remaining != queue:
            self._save_queue(queue_path, remaining)
        if published == 0:
            self.logger.info("定时任务执行完成，但无可发布条目")
