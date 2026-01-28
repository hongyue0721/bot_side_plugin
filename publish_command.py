from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional, Tuple

import httpx
import asyncio

from src.plugin_system import BaseCommand
from src.common.logger import get_logger
from src.common.database.database_model import Messages

from .content_generator import generate_post_from_topic

logger = get_logger("blog_publish_command")


def _build_plugin_config(get_config) -> dict:
    return {
        "generation": {
            "model": get_config("generation.model", "replyer"),
            "min_messages": get_config("generation.min_messages", 10),
            "target_length": get_config("generation.target_length", 300),
            "prompt_template": get_config("generation.prompt_template", ""),
            "command_prompt_template": get_config("generation.command_prompt_template", ""),
        },
        "schedule": {
            "timezone": get_config("schedule.timezone", "Asia/Shanghai"),
        },
    }


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_posts(posts_path: str) -> list:
    if not os.path.exists(posts_path):
        return []
    try:
        with open(posts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_posts(posts_path: str, posts: list) -> None:
    os.makedirs(os.path.dirname(posts_path), exist_ok=True)
    with open(posts_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def _normalize_url(url: str) -> str:
    return (url or "").rstrip("/")


async def _publish_remote(
    api_url: str,
    admin_password: str,
    title: str,
    content: str,
    timeout_seconds: int,
) -> Optional[int]:
    if not api_url:
        return None
    payload = {"title": title, "content": content}
    headers = {}
    if admin_password:
        headers["X-ADMIN-PASSWORD"] = admin_password
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(f"{_normalize_url(api_url)}/api/v1/posts", json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"远程发布失败: HTTP {resp.status_code} {resp.text}")
                return None
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"远程发布失败: {data}")
                return None
            record = data.get("data") or {}
            return int(record.get("id")) if record.get("id") is not None else None
    except Exception as exc:
        logger.error(f"远程发布异常: {exc}")
        return None


class BlogBaseCommand(BaseCommand):
    """博客插件基础命令类，提供通用功能"""

    async def _delete_cmd_message(self):
        """延迟删除触发指令的消息，避免污染上下文"""
        if not self.message or not hasattr(self.message, 'chat_stream') or not self.message.chat_stream:
            return
        
        chat_id = self.message.chat_stream.stream_id
        user_id = str(self.message.message_info.user_info.user_id)

        async def delayed_delete():
            await asyncio.sleep(2)  # 等待消息入库
            try:
                # 查找该用户在该群的最近一条消息（即指令消息）
                target_msgs = (Messages
                              .select()
                              .where(
                                  (Messages.chat_id == chat_id) &
                                  (Messages.user_id == user_id)
                              )
                              .order_by(Messages.time.desc())
                              .limit(1))
                
                if target_msgs:
                    for msg in target_msgs:
                        Messages.delete().where(Messages.message_id == msg.message_id).execute()
                        logger.info(f"已删除博客指令消息: {msg.message_id}")
            except Exception as e:
                logger.warning(f"删除指令消息失败: {e}")

        asyncio.create_task(delayed_delete())


class QQBlogPublishCommand(BlogBaseCommand):
    """通过 QQ 指令发布博客（远程 API 或本地 posts.json）"""

    command_name = "blog_publish"
    command_description = "发布博客文章（管理员）"
    command_pattern = r"^/blog\s+publish\s+(?P<title>[^|]{1,120})\s*\|\s*(?P<content>.+)$"

    async def execute(self) -> Tuple[bool, Optional[str], int]:
        # 权限检查
        admin_qqs = [str(x) for x in self.get_config("admin.admin_qqs", [])]
        user_id = str(self.message.message_info.user_info.user_id)
        is_group_chat = self.message.message_info.group_info is not None
        silent_in_group = bool(self.get_config("admin.silent_when_no_permission_in_group", True))

        if admin_qqs and user_id not in admin_qqs:
            if is_group_chat and silent_in_group:
                return False, "无权限", 2
            await self.send_text("❌ 你没有权限发布博客。")
            return False, "无权限", 2

        title = (self.matched_groups.get("title") or "").strip()
        content = (self.matched_groups.get("content") or "").strip()
        if not title or not content:
            await self.send_text("❌ 命令格式错误：/blog publish 标题 | 正文")
            return False, "参数错误", 2

        api_url = self.get_config("blog_api.url", "")
        admin_password = self.get_config("blog_api.admin_password", "")
        timeout_seconds = int(self.get_config("blog_api.timeout_seconds", 10))

        remote_id = await _publish_remote(api_url, admin_password, title, content, timeout_seconds)
        if remote_id:
            await self.send_text(f"✅ 已发布博客（远程）：{title} (ID={remote_id})")
            await self._delete_cmd_message()
            return True, "发布成功", 2

        posts_path = self.get_config("publish.posts_json_path", "blog_side_api/data/posts.json")
        posts_path = posts_path.replace("\\", "/")

        posts = _load_posts(posts_path)
        max_id = max([_safe_int(str(x.get("id", 0))) for x in posts], default=0)
        new_id = max_id + 1

        new_post = {
            "id": new_id,
            "title": title,
            "summary": content[:120] + ("..." if len(content) > 120 else ""),
            "content": content,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        posts.append(new_post)
        _save_posts(posts_path, posts)

        await self.send_text(f"✅ 已发布博客（本地）：{title} (ID={new_id})")
        await self._delete_cmd_message()
        return True, "发布成功", 2


class QQBlogGenerateCommand(BlogBaseCommand):
    """通过 QQ 指令生成并发布博客（LLM）"""

    command_name = "blog_generate"
    command_description = "生成并发布博客文章（管理员）"
    command_pattern = r"^/blog\s+generate\s+(?P<topic>.+)$"

    async def execute(self) -> Tuple[bool, Optional[str], int]:
        admin_qqs = [str(x) for x in self.get_config("admin.admin_qqs", [])]
        user_id = str(self.message.message_info.user_info.user_id)
        is_group_chat = self.message.message_info.group_info is not None
        silent_in_group = bool(self.get_config("admin.silent_when_no_permission_in_group", True))

        if admin_qqs and user_id not in admin_qqs:
            if is_group_chat and silent_in_group:
                return False, "无权限", 2
            await self.send_text("❌ 你没有权限生成博客。")
            return False, "无权限", 2

        topic = (self.matched_groups.get("topic") or "").strip()
        if not topic:
            await self.send_text("❌ 命令格式错误：/blog generate 主题")
            return False, "参数错误", 2

        plugin_config = _build_plugin_config(self.get_config)
        generated = await generate_post_from_topic(topic, plugin_config)
        if not generated:
            await self.send_text("❌ 生成失败，请稍后再试")
            return False, "生成失败", 2

        title, content = generated
        api_url = self.get_config("blog_api.url", "")
        admin_password = self.get_config("blog_api.admin_password", "")
        timeout_seconds = int(self.get_config("blog_api.timeout_seconds", 10))

        remote_id = await _publish_remote(api_url, admin_password, title, content, timeout_seconds)
        if remote_id:
            await self.send_text(f"✅ 已生成并发布博客（远程）：{title} (ID={remote_id})")
            await self._delete_cmd_message()
            return True, "发布成功", 2

        posts_path = self.get_config("publish.posts_json_path", "blog_side_api/data/posts.json")
        posts_path = posts_path.replace("\\", "/")

        posts = _load_posts(posts_path)
        max_id = max([_safe_int(str(x.get("id", 0))) for x in posts], default=0)
        new_id = max_id + 1

        new_post = {
            "id": new_id,
            "title": title,
            "summary": content[:120] + ("..." if len(content) > 120 else ""),
            "content": content,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        posts.append(new_post)
        _save_posts(posts_path, posts)

        await self.send_text(f"✅ 已生成并发布博客（本地）：{title} (ID={new_id})")
        await self._delete_cmd_message()
        return True, "发布成功", 2
