from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.plugin_system.apis import config_api, llm_api, message_api

logger = get_logger("blog_publish_generator")


def _get_timezone_now(timezone_str: str) -> datetime.datetime:
    try:
        import pytz

        tz = pytz.timezone(timezone_str)
        return datetime.datetime.now(tz)
    except ImportError:
        logger.error("pytz 未安装，使用系统时间")
        return datetime.datetime.now()
    except Exception as exc:
        logger.error(f"时区处理失败: {exc}，使用系统时间")
        return datetime.datetime.now()


def _get_date_range(date_str: str, timezone_str: str) -> Tuple[float, float]:
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        now = _get_timezone_now(timezone_str)
        date_obj = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        import pytz

        tz = pytz.timezone(timezone_str)
        start = tz.localize(date_obj.replace(hour=0, minute=0, second=0, microsecond=0))
        end = start + datetime.timedelta(days=1)
        return start.timestamp(), end.timestamp()
    except Exception:
        start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
        return start.timestamp(), end.timestamp()


def _build_timeline(messages: List[Any], bot_qq: str) -> str:
    if not messages:
        return ""
    parts: List[str] = []
    current_hour = None

    for msg in sorted(messages, key=lambda x: getattr(x, "time", 0)):
        msg_time = datetime.datetime.fromtimestamp(getattr(msg, "time", 0))
        hour = msg_time.hour
        if current_hour != hour:
            if 6 <= hour < 12:
                time_period = f"上午{hour}点"
            elif 12 <= hour < 18:
                time_period = f"下午{hour}点"
            else:
                time_period = f"晚上{hour}点"
            parts.append(f"\n【{time_period}】")
            current_hour = hour

        user_info = getattr(msg, "user_info", None)
        user_id = str(getattr(user_info, "user_id", "")) if user_info else ""
        nickname = getattr(user_info, "user_nickname", None) if user_info else None
        speaker = "我" if user_id and user_id == bot_qq else (nickname or "某人")

        content = getattr(msg, "processed_plain_text", "") or ""
        content = str(content).strip()
        if not content:
            continue
        if len(content) > 80:
            content = content[:80] + "..."
        parts.append(f"{speaker}: {content}")

    return "\n".join(parts).strip()


def _build_prompt(date_str: str, timeline: str, target_length: int, bot_name: str) -> str:
    return (
        f"今天是{date_str}，以下是今天的聊天记录摘要：\n"
        f"{timeline}\n\n"
        f"请根据聊天记录写一篇{target_length}字左右的博客日记，要求：\n"
        f"1. 用第一人称写作，口语化自然，不要流水账\n"
        f"2. 适当总结当天的情绪与重点话题\n"
        f"3. 不要输出任何前后缀、引号或解释\n\n"
        f"请严格按以下格式输出：\n"
        f"标题: <一句话标题>\n"
        f"正文: <日记正文>\n"
    )


def _build_topic_prompt(topic: str, target_length: int, bot_personality: str, bot_expression: str, current_time: str) -> str:
    return (
        f"你是{bot_personality}，现在是{current_time}。\n"
        f"请以“{topic}”为灵感，写一篇{target_length}字左右的中文博客。\n"
        f"请发挥想象力，内容不必局限于“{topic}”字面意思，可以发散思维，聊聊相关的生活细节、心情、天气或随机的有趣想法，让内容更具随机性和生活感。\n"
        f"要求：第一人称、口语化自然，不要流水账；{bot_expression}。\n"
        f"不要输出任何前后缀、引号或解释。\n\n"
        f"请严格按以下格式输出：\n"
        f"标题: <一句话标题（请根据实际生成的内容起标题，不要直接使用“{topic}”）>\n"
        f"正文: <博客正文>\n"
    )


def _parse_llm_output(text: str, fallback_title: str) -> Tuple[str, str]:
    if not text:
        return fallback_title, ""
    title = ""
    content = ""
    for line in text.splitlines():
        if line.startswith("标题:"):
            title = line.replace("标题:", "", 1).strip()
        elif line.startswith("正文:"):
            content = line.replace("正文:", "", 1).strip()
        elif not content and title:
            content = (content + "\n" + line).strip()

    if not title:
        title = fallback_title
    if not content:
        content = text.strip()
    return title, content


async def generate_post_from_messages(plugin_config: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    timezone_str = plugin_config.get("schedule", {}).get("timezone", "Asia/Shanghai")
    date_str = _get_timezone_now(timezone_str).strftime("%Y-%m-%d")
    start_time, end_time = _get_date_range(date_str, timezone_str)

    try:
        messages = message_api.get_messages_by_time(
            start_time=start_time,
            end_time=end_time,
            filter_mai=False,
        )
        if not isinstance(messages, list):
            messages = []
    except Exception as exc:
        logger.error(f"获取消息失败: {exc}")
        return None

    min_messages = int(plugin_config.get("generation", {}).get("min_messages", 10))
    if len(messages) < min_messages:
        logger.info(f"消息数量不足: {len(messages)} < {min_messages}")
        return None

    bot_qq = str(config_api.get_global_config("bot.qq_account", ""))
    bot_name = str(config_api.get_global_config("bot.nickname", "麦麦"))
    timeline = _build_timeline(messages, bot_qq)
    if not timeline:
        logger.info("时间线为空，跳过生成")
        return None

    # 参考 diary_plugin 逻辑：使用随机目标字数范围，增加自然感
    base_target = int(plugin_config.get("generation", {}).get("target_length", 300))
    
    # 动态计算目标字数：在 base_target 基础上浮动 +/- 50 字
    import random
    target_length = random.randint(max(100, base_target - 50), base_target + 50)

    prompt = plugin_config.get("generation", {}).get("prompt_template") or _build_prompt(
        date_str, timeline, target_length, bot_name
    )

    models = llm_api.get_available_models()
    model_key = plugin_config.get("generation", {}).get("model", "replyer")
    model_config = models.get(model_key) if isinstance(models, dict) else None
    if not model_config and isinstance(models, dict) and models:
        model_config = list(models.values())[0]

    if not model_config:
        logger.error("未找到可用模型")
        return None

    try:
        success, content, _, model_name = await llm_api.generate_with_model(
            prompt=prompt,
            model_config=model_config,
            request_type="plugin.blog_publish_generation",
        )
        if not success or not content:
            logger.error("LLM 生成失败")
            return None
        fallback_title = f"{date_str} 日记"
        title, body = _parse_llm_output(str(content), fallback_title)
        if not body:
            return None
        
        logger.info(f"生成成功，模型: {model_name}")
        return title, body
    except Exception as exc:
        logger.error(f"LLM 调用失败: {exc}")
        return None


async def generate_post_from_topic(topic: str, plugin_config: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    if not topic:
        return None

    current_time = _get_timezone_now(plugin_config.get("schedule", {}).get("timezone", "Asia/Shanghai")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    bot_personality = str(config_api.get_global_config("personality.personality", "一个机器人"))
    bot_expression = str(config_api.get_global_config("personality.reply_style", "内容积极向上"))

    # 参考 diary_plugin 逻辑：使用随机目标字数范围
    base_target = int(plugin_config.get("generation", {}).get("target_length", 300))
    
    import random
    target_length = random.randint(max(100, base_target - 50), base_target + 50)

    custom_template = plugin_config.get("generation", {}).get("command_prompt_template")
    prompt = custom_template or _build_topic_prompt(topic, target_length, bot_personality, bot_expression, current_time)

    models = llm_api.get_available_models()
    model_key = plugin_config.get("generation", {}).get("model", "replyer")
    model_config = models.get(model_key) if isinstance(models, dict) else None
    if not model_config and isinstance(models, dict) and models:
        model_config = list(models.values())[0]

    if not model_config:
        logger.error("未找到可用模型")
        return None

    try:
        success, content, _, model_name = await llm_api.generate_with_model(
            prompt=prompt,
            model_config=model_config,
            request_type="plugin.blog_publish_generation",
        )
        if not success or not content:
            logger.error("LLM 生成失败")
            return None
        fallback_title = f"{topic}"
        title, body = _parse_llm_output(str(content), fallback_title)
        if not body:
            return None
        
        logger.info(f"生成成功，模型: {model_name}")
        return title, body
    except Exception as exc:
        logger.error(f"LLM 调用失败: {exc}")
        return None
