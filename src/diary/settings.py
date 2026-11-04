"""Validated diary scheduling settings, separate from market credentials."""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = dict(
    enabled=True,
    time="00:10",
    timezone="Asia/Shanghai",
    min_logs=2,
    chat_only=False,
    history_count=40,
)


def settings(values=None):
    result = {**DEFAULTS, **(values or {})}
    if set(result) != set(DEFAULTS):
        raise ValueError("日记设置包含未知字段")
    if any(type(result[key]) is not bool for key in ("enabled", "chat_only")):
        raise ValueError("日记开关格式无效")
    for key, maximum in (("min_logs", 10000), ("history_count", 100)):
        if type(result[key]) is not int or not 0 <= result[key] <= maximum:
            raise ValueError("日志阈值须在0～10000，聊天条数须在0～100之间")
    if not isinstance(result["time"], str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", result["time"]
    ):
        raise ValueError("日记时间须为24小时制 HH:MM")
    try:
        ZoneInfo(result["timezone"])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("请选择有效时区，如 Asia/Shanghai") from None
    return result


def bounds(day, zone):
    value = date.fromisoformat(day)
    tz = ZoneInfo(zone)
    return (
        datetime.combine(value, time(), tz).timestamp(),
        datetime.combine(value + timedelta(days=1), time(), tz).timestamp(),
    )


def due_before(now, config):
    local = datetime.fromtimestamp(now, ZoneInfo(config["timezone"]))
    # Before today's writing time only days before yesterday are due.
    return local.date() - timedelta(
        days=1 if local.strftime("%H:%M") >= config["time"] else 2
    )
