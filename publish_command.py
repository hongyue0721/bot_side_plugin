from __future__ import annotations

import json
import os
import time
from typing import Optional, Tuple

from src.plugin_system import BaseCommand
from src.common.logger import get_logger

logger = get_logger("blog_publish_command")


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


class QQBlogPublishCommand(BaseCommand):
    """通过 QQ 指令发布博客（写入本地 posts.json）"""

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
            "author": "MaiBot",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        posts.append(new_post)
        _save_posts(posts_path, posts)

        await self.send_text(f"✅ 已发布博客：{title} (ID={new_id})")
        return True, "发布成功", 2
