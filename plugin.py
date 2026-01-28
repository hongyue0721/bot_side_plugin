from __future__ import annotations

import asyncio
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo

from .publish_command import QQBlogPublishCommand, QQBlogGenerateCommand
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
        "blog_api": "远程博客 API 配置",
        "generation": "定时内容生成配置",
    }

    config_schema = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.2.0", description="配置文件版本"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "debug_mode": ConfigField(type=bool, default=False, description="调试模式，输出详细日志"),
        },
        "admin": {
            "admin_qqs": ConfigField(
                type=list,
                default=[],
                description="允许发布博客的管理员 QQ 号",
                item_type="string",
                placeholder="输入 QQ 号",
            ),
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
                description="本地博客 posts.json 路径（仅本地模式使用）",
            ),
        },
        "blog_api": {
            "url": ConfigField(type=str, default="http://127.0.0.1:8000", description="博客 API 地址"),
            "admin_password": ConfigField(
                type=str,
                default="",
                description="管理端密码（X-ADMIN-PASSWORD）",
                input_type="password",
            ),
            "timeout_seconds": ConfigField(type=int, default=10, description="HTTP 超时时间（秒）"),
        },
        "generation": {
            "model": ConfigField(type=str, default="replyer", description="生成模型键名"),
            "min_messages": ConfigField(type=int, default=10, description="最少消息数（不足则跳过生成）"),
            "target_length": ConfigField(type=int, default=300, description="目标字数（用于生成提示）"),
            "prompt_template": ConfigField(
                type=str,
                default="",
                description="自定义提示词模板（留空使用默认模板）",
                input_type="textarea",
                rows=5,
            ),
            "command_prompt_template": ConfigField(
                type=str,
                default="",
                description="指令生成的提示词模板（留空使用默认模板）",
                input_type="textarea",
                rows=5,
            ),
        },
        "schedule": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用定时发布"),
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
            "tasks": ConfigField(
                type=list,
                default=[
                    {"time": "08:00", "type": "topic", "topic": "早安，新的一天"},
                    {"time": "23:30", "type": "summary"},
                ],
                description="定时任务列表",
                item_type="object",
                item_fields={
                    "time": {"type": "string", "label": "执行时间 (HH:MM)", "placeholder": "08:00"},
                    "type": {
                        "type": "string",
                        "label": "任务类型",
                        "choices": ["topic", "summary", "queue"],
                    },
                    "topic": {"type": "string", "label": "话题 (仅 topic 类型有效)", "placeholder": "早安"},
                },
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
            (QQBlogGenerateCommand.get_command_info(), QQBlogGenerateCommand),
        ]
