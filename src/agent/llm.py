"""Platform or private OpenAI-compatible provider, using the host's tool loop."""

import copy
from urllib.parse import urlsplit

DEFAULTS = dict(
    mode="platform",
    debug_prompt=False,
    provider_id="",
    api_base="",
    model="",
    api_key="",
    headers={},
    timeout=120,
)


def settings(current=None, changes=None):
    values = {**DEFAULTS, **(current or {})}
    if changes is not None:
        if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
            raise ValueError("模型接口设置包含未知字段")
        values.update({k: v for k, v in changes.items() if k != "api_key" or v != ""})
    if type(values["debug_prompt"]) is not bool:
        raise ValueError("提示词调试开关须为布尔值")
    if values["mode"] not in ("platform", "custom"):
        raise ValueError("请选择平台模型或自定义兼容接口")
    for key in ("provider_id", "api_base", "model", "api_key"):
        if (
            not isinstance(values[key], str)
            or len(values[key]) > 4000
            or any(c in values[key] for c in "\r\n")
        ):
            raise ValueError("模型接口字段须为单行文字")
        values[key] = values[key].strip()
    if type(values["timeout"]) is not int or not 10 <= values["timeout"] <= 180:
        raise ValueError("模型超时须为10～180秒")
    headers = values["headers"]
    if (
        not isinstance(headers, dict)
        or len(headers) > 30
        or not all(
            isinstance(k, str)
            and isinstance(v, str)
            and k
            and not any(c in k + v for c in "\r\n")
            and len(k + v) <= 4000
            for k, v in headers.items()
        )
    ):
        raise ValueError("自定义请求头须为字符串键值JSON对象")
    if (
        changes is not None
        and values["mode"] == "platform"
        and not values["provider_id"]
    ):
        raise ValueError("请选择平台模型")
    if values["mode"] == "custom":
        url = urlsplit(values["api_base"])
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
            or url.query
        ):
            raise ValueError(
                "请填写有效的兼容接口Base URL，例如 https://example.com/v1"
            )
        if not values["model"]:
            raise ValueError("请填写自定义模型名")
    return values


def public(values):
    result = settings(values)
    return {k: v for k, v in result.items() if k not in ("api_key", "headers")} | dict(
        key_configured=bool(result["api_key"]),
        headers_configured=bool(result["headers"]),
    )


def ensure_available(plugin, game):
    config = settings(plugin.settings().get("llm"))
    if config["mode"] == "platform":
        pid = config["provider_id"] or game.get("provider", "")
        if not pid or not plugin.context.get_provider_by_id(pid):
            raise ValueError("请先选择可用的平台决策模型或配置自定义接口")
    return config


class ProviderScope:
    def __init__(self, original, provider):
        self.original, self.provider = original, provider

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def get_provider_by_id(self, pid):
        if pid == "kurumi-private-llm":
            return self.provider
        return await self.original.get_provider_by_id(pid)


def checked_response(response):
    if response is None or getattr(response, "role", None) == "err":
        raise ValueError("模型服务返回错误，任务未完成，请查看AstrBot模型日志")
    return response


async def tool_loop(plugin, game, **kwargs):
    config = ensure_available(plugin, game)
    if config["debug_prompt"]:
        from astrbot.api import logger
        from ..core.engine import dump
        from ..diary.store import redact

        logger.info(
            "[Kurumi][LLM完整提示词] %s",
            redact(
                dump(
                    dict(
                        instance=game["id"],
                        mode=config["mode"],
                        provider=config["provider_id"] or game.get("provider", "")
                        if config["mode"] == "platform"
                        else config["model"],
                        system_prompt=kwargs.get("system_prompt", ""),
                        contexts=kwargs.get("contexts", []),
                        prompt=kwargs.get("prompt", ""),
                    )
                )
            ),
        )
    if config["mode"] == "platform":
        return checked_response(
            await plugin.context.tool_loop_agent(
                chat_provider_id=config["provider_id"] or game["provider"], **kwargs
            )
        )
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    provider = ProviderOpenAIOfficial(
        dict(
            id="kurumi-private-llm",
            type="openai_chat_completion",
            key=[config["api_key"] or "unused"],
            api_base=config["api_base"],
            model=config["model"],
            timeout=config["timeout"],
            custom_headers=config["headers"],
        ),
        dict(request_max_retries=1),
    )
    # Each call has an isolated Context copy; never replace the host's global provider.
    context = copy.copy(plugin.context)
    context.provider_manager = ProviderScope(plugin.context.provider_manager, provider)
    try:
        return checked_response(
            await context.tool_loop_agent(
                chat_provider_id="kurumi-private-llm", **kwargs
            )
        )
    finally:
        await provider.terminate()
