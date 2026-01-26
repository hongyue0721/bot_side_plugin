from __future__ import annotations

import asyncio
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo

from .publish_command import QQBlogPublishCommand
from .scheduler import BlogPublishScheduler
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger

logger = get_logger("blog_publish_plugin")


@register_plugin
class BlogPublishPlugin(BasePlugin):
    """QQ 指令发布博客插件（含定时发布）"""

    plugin_name = "blog_publish_plugin"
    plugin_description = "通过 QQ 指令发布博客内容（含定时发布）"
    plugin_author = "YourName"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies: List[str] = []
    python_dependencies: List[str] = ["httpx", "pytz"]

    config_section_descriptions = {
        "plugin": "插件基础配置",
        "admin": "管理员权限配置",
        "publish": "发布博客配置",
        "schedule": "定时发布配置",
    }

    config_schema = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.1.0", description="配置文件版本"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
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
        "schedule": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用定时发布"),
            "schedule_time": ConfigField(type=str, default="23:30", description="每日执行时间(HH:MM)"),
            "timezone": ConfigField(type=str, default="Asia/Shanghai", description="时区设置"),
            "queue_json_path": ConfigField(
                type=str,
                default="bot_side_plugin/data/scheduled_posts.json",
                description="定时发布队列JSON路径",
            ),
            "max_posts_per_run": ConfigField(
                type=int,
                default=1,
                description="每次执行最多发布条数",
            ),
        },
    }

    def __init__(self, plugin_dir: str, **kwargs):
        super().__init__(plugin_dir, **kwargs)
        self.scheduler: BlogPublishScheduler | None = None
        self.logger = get_logger("BlogPublishPlugin")
        self.scheduler = BlogPublishScheduler(self)
        asyncio.create_task(self._start_scheduler_after_delay())

    async def _start_scheduler_after_delay(self) -> None:
        await asyncio.sleep(10)
        if not self.get_config("plugin.enabled", True):
            self.logger.info("插件未启用，跳过定时调度器启动")
            return
        if not self.get_config("schedule.enabled", False):
            self.logger.info("定时发布未启用，跳过调度器启动")
            return
        if self.scheduler:
            await self.scheduler.start()

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        if not self.get_config("plugin.enabled", True):
            return []
        return [
            (QQBlogPublishCommand.get_command_info(), QQBlogPublishCommand),
        ]
