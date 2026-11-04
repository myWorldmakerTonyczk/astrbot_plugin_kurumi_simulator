"""Notification preferences and hard quiet-hour delivery boundaries."""

import random
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = dict(
    enabled=True,
    analysis=False,
    liquidation=True,
    margin_call=True,
    deposit=True,
    end=True,
    use_window=False,
    random_delay=False,
    window_start="09:00",
    window_end="22:00",
    quiet_start="00:00",
    quiet_end="07:00",
    timezone="Asia/Shanghai",
)
BOOLS = {key for key, value in DEFAULTS.items() if isinstance(value, bool)}


def validate(values=None):
    if values is not None and not isinstance(values, dict):
        raise ValueError("通知设置须为对象")
    result = {**DEFAULTS, **(values or {})}
    if set(result) != set(DEFAULTS):
        raise ValueError("通知设置包含未知字段")
    if any(type(result[key]) is not bool for key in BOOLS):
        raise ValueError("通知开关须为布尔值")
    for key in ("window_start", "window_end", "quiet_start", "quiet_end"):
        if not isinstance(result[key], str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", result[key]
        ):
            raise ValueError("通知时间须为24小时制HH:MM")
    if result["quiet_start"] == result["quiet_end"]:
        raise ValueError("免打扰开始与结束时间不能相同")
    if result["window_start"] == result["window_end"]:
        raise ValueError("汇报时段开始与结束不能相同")
    try:
        ZoneInfo(result["timezone"])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("通知时区无效") from None
    if result["use_window"]:
        # No random draw is needed to validate whether a non-quiet slot exists.
        delivery_time(
            datetime(2026, 1, 1, tzinfo=ZoneInfo(result["timezone"])).timestamp(),
            result,
            "analysis",
            randomize=False,
        )
    return result


def config(game):
    return validate(game.get("notifications"))


def quiet(now, values):
    hhmm = datetime.fromtimestamp(now, ZoneInfo(values["timezone"])).strftime("%H:%M")
    start, end = values["quiet_start"], values["quiet_end"]
    return start <= hhmm < end if start < end else hhmm >= start or hhmm < end


def interval(day, start, end, tz):
    begin = datetime.combine(day, time.fromisoformat(start), tz)
    finish = datetime.combine(
        day + timedelta(days=end <= start), time.fromisoformat(end), tz
    )
    return begin.timestamp(), finish.timestamp()


def delivery_time(now, values, kind, *, randomize=True):
    tz = ZoneInfo(values["timezone"])
    day = datetime.fromtimestamp(now, tz).date()
    quiet_intervals = [
        interval(
            day + timedelta(days=i), values["quiet_start"], values["quiet_end"], tz
        )
        for i in range(-1, 5)
    ]
    use_window = kind == "analysis" and values["use_window"]
    for offset in range(-1 if use_window else 0, 4):
        date = day + timedelta(days=offset)
        if use_window:
            start, end = interval(
                date, values["window_start"], values["window_end"], tz
            )
        else:
            start = datetime.combine(date, time(), tz).timestamp()
            end = datetime.combine(date + timedelta(days=1), time(), tz).timestamp()
        slots = [(max(start, now), end)] if end > max(start, now) else []
        for qs, qe in quiet_intervals:
            pieces = []
            for a, b in slots:
                if qe <= a or qs >= b:
                    pieces.append((a, b))
                else:
                    if a < qs:
                        pieces.append((a, qs))
                    if qe < b:
                        pieces.append((qe, b))
            slots = pieces
        if slots:
            if use_window and randomize and values["random_delay"]:
                total = sum(b - a for a, b in slots)
                distance = random.random() * total
                for a, b in slots:
                    if distance < b - a:
                        return a + distance
                    distance -= b - a
            return slots[0][0]
    raise ValueError("汇报时段全部位于免打扰黑名单，请调整时间")
