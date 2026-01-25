from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.plugin_system.apis import llm_api, config_api
from src.common.logger import get_logger

logger = get_logger("blog_comment_reply.monitor")


class CommentMonitor:
    """定时监控博客评论并自动回复"""

    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_since = 0
        self._processed_cache: Dict[str, float] = {}
        self._processed_counts: Dict[str, int] = {}
        self._consecutive_failures = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._init_since()
        self._task = asyncio.create_task(self._loop())
        logger.info("评论监控任务已启动")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("评论监控任务已停止")

    def _init_since(self) -> None:
        initial_since = self.plugin.get_config("monitor.initial_since", 0)
        if initial_since and int(initial_since) > 0:
            self._last_since = int(initial_since)
        else:
            self._last_since = int(time.time())

    async def _loop(self) -> None:
        interval = int(self.plugin.get_config("monitor.check_interval", 60))
        while self._running:
            try:
                await self._check_comments()
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                logger.error(f"监控循环异常: {exc}")
                if self._consecutive_failures >= 5:
                    logger.warning("连续失败过多，进入短暂冷却")
                    await asyncio.sleep(30)
            await asyncio.sleep(max(5, interval))

    async def _check_comments(self) -> None:
        if not self.plugin.get_config("plugin.enable", True):
            return
        if not self.plugin.get_config("monitor.enable_monitor", True):
            return

        since = self._last_since
        comments = await self._fetch_comments(since)
        if not comments:
            return

        max_created_ts = since
        for comment in comments:
            comment_id = str(comment.get("id"))
            created_at = comment.get("created_at")
            created_ts = self._parse_created_at(created_at) or int(time.time())
            max_created_ts = max(max_created_ts, created_ts)

            if await self._should_skip(comment):
                continue

            if not self.plugin.get_config("reply.enable_reply", True):
                self._mark_processed(comment_id)
                continue

            if self.plugin.get_config("security.enable_review", False):
                logger.info(f"启用人工审核，跳过自动回复: {comment_id}")
                self._mark_processed(comment_id)
                continue

            prompt = await self._build_prompt(comment)
            reply = await self._generate_reply(prompt)
            if not reply:
                continue

            success = await self._submit_reply(comment, reply)
            if success:
                self._mark_processed(comment_id)

        self._last_since = max_created_ts
        self._cleanup_cache()

    async def _fetch_comments(self, since: int) -> List[Dict[str, Any]]:
        base_url = self.plugin.get_config("blog_api.blog_api_url", "").rstrip("/")
        api_key = self.plugin.get_config("blog_api.blog_api_key", "")
        timeout = int(self.plugin.get_config("blog_api.api_timeout", 10))
        retry_times = int(self.plugin.get_config("blog_api.retry_times", 3))
        retry_delay = int(self.plugin.get_config("blog_api.retry_delay", 2))

        if not base_url:
            logger.error("blog_api_url 未配置")
            return []

        url = f"{base_url}/api/v1/comments/pending"
        headers = {"X-API-KEY": api_key} if api_key else {}
        params = {"since": since}

        for attempt in range(retry_times):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code") != 0:
                        logger.error(f"拉取评论失败: {data}")
                        return []
                    return data.get("data", [])
            except Exception as exc:
                logger.warning(f"拉取评论失败({attempt + 1}/{retry_times}): {exc}")
                await asyncio.sleep(retry_delay)
        return []

    async def _should_skip(self, comment: Dict[str, Any]) -> bool:
        comment_id = str(comment.get("id"))
        if self.plugin.get_config("dedup.enable_dedup", True):
            if comment_id in self._processed_cache:
                return True

        forbidden_words = self.plugin.get_config("security.forbidden_words", []) or []
        content = str(comment.get("content", ""))
        for word in forbidden_words:
            if word and word in content:
                logger.info(f"命中禁评词，跳过评论 {comment_id}")
                return True

        allowed_post_ids = self.plugin.get_config("security.allowed_post_ids", []) or []
        if allowed_post_ids:
            if str(comment.get("post_id")) not in {str(x) for x in allowed_post_ids}:
                return True

        blocked_names = self.plugin.get_config("security.blocked_visitor_names", []) or []
        if str(comment.get("visitor_name")) in {str(x) for x in blocked_names}:
            return True

        max_replies = int(self.plugin.get_config("security.max_replies_per_comment", 1))
        if max_replies > 0:
            count = self._processed_counts.get(comment_id, 0)
            if count >= max_replies:
                return True

        return False

    async def _build_prompt(self, comment: Dict[str, Any]) -> str:
        template = self.plugin.get_config("reply.reply_prompt_template", "")
        max_summary_length = int(self.plugin.get_config("reply.max_summary_length", 500))

        post_summary = str(comment.get("post_summary", ""))
        if len(post_summary) > max_summary_length:
            post_summary = post_summary[:max_summary_length] + "..."

        base_prompt = template.format(
            post_title=comment.get("post_title", ""),
            post_summary=post_summary,
            visitor_name=comment.get("visitor_name", "访客"),
            comment=comment.get("content", ""),
        )

        persona = _resolve_persona()
        return persona + "\n" + base_prompt

    async def _generate_reply(self, prompt: str) -> str:
        timeout = int(self.plugin.get_config("reply.reply_timeout", 30))
        model = llm_api.get_available_models().get("replyer")
        if not model:
            logger.error("未找到默认 replyer 模型")
            return ""

        try:
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model,
                request_type="plugin.blog_comment_reply",
                timeout=timeout,
            )
        except TypeError:
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model,
                request_type="plugin.blog_comment_reply",
            )
        if not success or not content:
            logger.error("生成回复失败")
            return ""
        return content.strip()

    async def _submit_reply(self, comment: Dict[str, Any], reply: str) -> bool:
        base_url = self.plugin.get_config("blog_api.blog_api_url", "").rstrip("/")
        api_key = self.plugin.get_config("blog_api.blog_api_key", "")
        timeout = int(self.plugin.get_config("blog_api.api_timeout", 10))
        retry_times = int(self.plugin.get_config("blog_api.retry_times", 3))
        retry_delay = int(self.plugin.get_config("blog_api.retry_delay", 2))

        url = f"{base_url}/api/v1/comments"
        headers = {"X-API-KEY": api_key} if api_key else {}
        payload = {
            "post_id": comment.get("post_id"),
            "parent_id": comment.get("id"),
            "author": "bot",
            "content": reply,
        }

        for attempt in range(retry_times):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code") != 0:
                        logger.error(f"回复提交失败: {data}")
                        return False
                    return True
            except Exception as exc:
                logger.warning(f"提交回复失败({attempt + 1}/{retry_times}): {exc}")
                await asyncio.sleep(retry_delay)
        return False

    def _mark_processed(self, comment_id: str) -> None:
        self._processed_cache[comment_id] = time.time()
        self._processed_counts[comment_id] = self._processed_counts.get(comment_id, 0) + 1

    def _cleanup_cache(self) -> None:
        ttl = int(self.plugin.get_config("dedup.cache_ttl", 86400))
        cache_size = int(self.plugin.get_config("dedup.cache_size", 200))
        now = time.time()

        expired = [k for k, v in self._processed_cache.items() if now - v > ttl]
        for key in expired:
            self._processed_cache.pop(key, None)
            self._processed_counts.pop(key, None)

        if len(self._processed_cache) > cache_size:
            sorted_items = sorted(self._processed_cache.items(), key=lambda x: x[1])
            for key, _ in sorted_items[: len(self._processed_cache) - cache_size]:
                self._processed_cache.pop(key, None)
                self._processed_counts.pop(key, None)

    def _parse_created_at(self, created_at: Any) -> Optional[int]:
        try:
            if not created_at:
                return None
            if isinstance(created_at, (int, float)):
                return int(created_at)
            from datetime import datetime

            return int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None


def _resolve_persona() -> str:
    """从主程序读取人格配置并拼接系统提示词"""
    personality = config_api.get_global_config("personality.personality", "")
    reply_style = config_api.get_global_config("personality.reply_style", "")
    plan_style = config_api.get_global_config("personality.plan_style", "")
    states = config_api.get_global_config("personality.states", [])
    state_probability = config_api.get_global_config("personality.state_probability", 0.0)

    active_persona = personality
    try:
        import random

        if states and random.random() < float(state_probability):
            active_persona = random.choice(states)
    except Exception:
        pass

    parts = [
        f"人格设定: {active_persona}",
        f"表达风格: {reply_style}",
        f"说话规则: {plan_style}",
    ]
    return "\n".join([p for p in parts if p])
