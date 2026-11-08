"""Task-level rate limits and independent risk-to-LLM triggers."""

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from ..core.availability import WEEKEND


DEFAULTS = dict(
    **WEEKEND,
    cooldown=600,
    hourly_limit=6,
    stop_loss=True,
    take_profit=True,
    liquidation=True,
    margin_call=True,
    end=True,
)


def settings(values=None):
    if values is not None and not isinstance(values, dict):
        raise ValueError("看盘触发设置须为对象")
    result = {**DEFAULTS, **(values or {})}
    if set(result) != set(DEFAULTS):
        raise ValueError("看盘触发设置包含未知字段")
    if type(result["cooldown"]) is not int or not 600 <= result["cooldown"] <= 86400:
        raise ValueError("看盘任务最短间隔须为10分钟～24小时")
    if type(result["hourly_limit"]) is not int or not 1 <= result["hourly_limit"] <= 6:
        raise ValueError("每实例每小时看盘上限须为1～6次")
    if any(
        type(result[k]) is not bool
        for k in DEFAULTS
        if k not in ("cooldown", "hourly_limit", "weekend_zone", "weekend_start_day", "weekend_end_day", "weekend_start_time", "weekend_end_time")
    ):
        raise ValueError("风险事件触发开关须为布尔值")
    try:
        ZoneInfo(result["weekend_zone"])
        for key in ("weekend_start_time", "weekend_end_time"):
            clock = result[key]
            if not isinstance(clock, str) or len(clock) != 5:
                raise ValueError()
            time.fromisoformat(clock)
        for key in ("weekend_start_day", "weekend_end_day"):
            if type(result[key]) is not int or not 0 <= result[key] <= 6:
                raise ValueError()
        if (result["weekend_start_day"], result["weekend_start_time"]) == (result["weekend_end_day"], result["weekend_end_time"]):
            raise ValueError()
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValueError("休市时段或时区无效，开始与结束不能相同") from None
    return result
