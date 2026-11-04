"""Task-level rate limits and independent risk-to-LLM triggers."""

DEFAULTS = dict(
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
        if k not in ("cooldown", "hourly_limit")
    ):
        raise ValueError("风险事件触发开关须为布尔值")
    return result
