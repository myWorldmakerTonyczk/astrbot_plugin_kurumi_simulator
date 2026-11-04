"""Validated server-side quote settings and a credential-free View payload."""

from .market import source, validate_url
from .config import DEFAULT_URLS, LABELS


def merge_settings(current, changes):
    keys = {
        "history_source",
        "market_source",
        "market_key",
        "market_account",
        "biquote_url",
        "sina_url",
    }
    if not isinstance(changes, dict) or set(changes) - keys:
        raise ValueError("行情设置包含未知字段")
    result = dict(current)
    for key, value in changes.items():
        if (
            not isinstance(value, str)
            or len(value) > 2000
            or any(c in value for c in "\r\n")
        ):
            raise ValueError("行情设置格式无效")
        value = value.strip()
        if key in ("market_key", "market_account") and not value:
            continue
        result[key] = value
    provider = source(result)
    if provider not in LABELS:
        raise ValueError("请选择支持的行情源")
    result["market_source"] = provider
    result.setdefault("history_source", "frankfurter")
    if result["history_source"] not in ("frankfurter", "market"):
        raise ValueError("历史来源无效")
    for provider, default in DEFAULT_URLS.items():
        result[provider + "_url"] = result.get(provider + "_url") or default
        validate_url(result[provider + "_url"])
    return result


def public_settings(settings):
    return dict(
        market_source=source(settings),
        history_source=settings.get("history_source", "frankfurter"),
        configured=bool(settings.get("market_key")),
        market_account=settings.get("market_account", ""),
        defaults=DEFAULT_URLS,
        **{p + "_url": settings.get(p + "_url") or u for p, u in DEFAULT_URLS.items()},
    )
