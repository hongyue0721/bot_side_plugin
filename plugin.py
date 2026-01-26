from __future__ import annotations

import asyncio
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo, CommandInfo, BaseCommand

from .publish_command import QQBlogPublishCommand
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger

logger = get_logger("blog_comment_reply")


@register_plugin
class BlogCommentReplyPlugin(BasePlugin):
    """QQ 指令发布博客插件（MaiBot）"""

    plugin_name = "blog_publish_plugin"
    plugin_description = "通过 QQ 指令发布博客内容"
    plugin_author = "YourName"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies: List[str] = []
    python_dependencies: List[str] = ["httpx"]

    config_section_descriptions = {
        "plugin": "插件基础配置",
        "admin": "管理员权限配置",
        "publish": "发布博客配置",
    }

    config_schema = {
        "plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用插件"),
            "debug_mode": ConfigField(type=bool, default=False, description="调试模式，输出详细日志"),
        },
        "admin": {
            "admin_qqs": ConfigField(type=list, default=[], description="允许发布博客的管理员 QQ 号"),
            "silent_when_no_permission_in_group": ConfigField(
                type=bool,
                default=True,
                description="群聊中无权限时是否静默处理",
            ),
        },
        "publish": {
            "posts_json_path": ConfigField(
                type=str,
                default="blog_side_api/data/posts.json",
                description="本地博客 posts.json 路径",
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (QQBlogPublishCommand.get_command_info(), QQBlogPublishCommand),
        ]
