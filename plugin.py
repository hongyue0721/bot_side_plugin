from __future__ import annotations

import asyncio
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo, CommandInfo, BaseCommand

from .publish_command import QQBlogPublishCommand
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger

from .monitor import CommentMonitor

logger = get_logger("blog_comment_reply")


@register_plugin
class BlogCommentReplyPlugin(BasePlugin):
    """博客评论自动回复插件（MaiBot）"""

    plugin_name = "blog_comment_reply_plugin"
    plugin_description = "定时拉取博客评论并自动生成回复写回"
    plugin_author = "YourName"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies: List[str] = []
    python_dependencies: List[str] = ["httpx"]

    config_section_descriptions = {
        "plugin": "插件基础配置",
        "blog_api": "博客 API 配置",
        "monitor": "监控任务配置",
        "reply": "回复策略配置",
        "dedup": "去重与缓存配置",
        "security": "安全与审核配置",
        "admin": "管理员权限配置",
        "publish": "发布博客配置",
    }

    config_schema = {
        "plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用插件"),
            "debug_mode": ConfigField(type=bool, default=False, description="调试模式，输出详细日志"),
        },
        "blog_api": {
            "blog_api_url": ConfigField(type=str, default="", description="博客 API 基础地址", required=True),
            "blog_api_key": ConfigField(
                type=str,
                default="",
                description="API 认证 Token",
                required=True,
                input_type="password",
            ),
            "api_timeout": ConfigField(type=int, default=10, description="API 请求超时（秒）"),
            "retry_times": ConfigField(type=int, default=3, description="请求失败重试次数"),
            "retry_delay": ConfigField(type=int, default=2, description="重试间隔（秒）"),
        },
        "monitor": {
            "enable_monitor": ConfigField(type=bool, default=True, description="是否启用自动监控"),
            "check_interval": ConfigField(type=int, default=60, description="检查新评论间隔（秒）"),
            "initial_since": ConfigField(type=int, default=0, description="初始 since 时间戳（0 表示从现在开始）"),
        },
        "reply": {
            "enable_reply": ConfigField(type=bool, default=True, description="是否启用自动回复"),
            "reply_prompt_template": ConfigField(
                type=str,
                default=(
                    "你是博客作者，你的博客文章《{post_title}》摘要如下：\n"
                    "{post_summary}\n"
                    "访客「{visitor_name}」评论说：「{comment}」\n"
                    "请你以作者身份，对这条评论做一个简短、友好、自然的回复。\n"
                    "要求：口吻与你的表达风格一致，不要刻意卖弄知识，不要啰嗦，不要输出多余内容（如冒号、引号、@等）。"
                ),
                description="回复提示词模板",
                input_type="textarea",
            ),
            "max_summary_length": ConfigField(type=int, default=500, description="文章摘要最大长度"),
            "reply_timeout": ConfigField(type=int, default=30, description="LLM 回复超时（秒）"),
        },
        "dedup": {
            "enable_dedup": ConfigField(type=bool, default=True, description="是否启用去重"),
            "cache_size": ConfigField(type=int, default=200, description="缓存大小"),
            "cache_ttl": ConfigField(type=int, default=86400, description="缓存过期时间（秒）"),
        },
        "security": {
            "enable_review": ConfigField(type=bool, default=False, description="是否启用人工审核"),
            "forbidden_words": ConfigField(type=list, default=[], description="禁评词库"),
            "max_replies_per_comment": ConfigField(type=int, default=1, description="单评论最大回复次数"),
            "allowed_post_ids": ConfigField(type=list, default=[], description="仅处理这些文章 ID（空表示全部）"),
            "blocked_visitor_names": ConfigField(type=list, default=[], description="屏蔽访客名单"),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor: CommentMonitor | None = None

        if self.get_config("plugin.enable", True):
            self.enable_plugin = True
            if self.get_config("monitor.enable_monitor", True):
                self.monitor = CommentMonitor(self)
                asyncio.create_task(self._start_monitor_after_delay())
        else:
            self.enable_plugin = False

    async def _start_monitor_after_delay(self):
        await asyncio.sleep(5)
        if self.monitor:
            await self.monitor.start()

    async def on_enable(self):
        if self.monitor is None and self.get_config("monitor.enable_monitor", True):
            self.monitor = CommentMonitor(self)
            await self.monitor.start()

    async def on_disable(self):
        if self.monitor:
            await self.monitor.stop()

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (QQBlogPublishCommand.get_command_info(), QQBlogPublishCommand),
        ]
