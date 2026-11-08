"""Weekly forex closure and configurable autonomous decision break."""
from datetime import datetime
from zoneinfo import ZoneInfo

WEEKEND = dict(weekend_pause=True, weekend_zone="America/New_York",
               weekend_start_day=4, weekend_start_time="16:59",
               weekend_end_day=6, weekend_end_time="17:05")


def inside_weekly_window(now, config):
    local = datetime.fromtimestamp(now, ZoneInfo(config["weekend_zone"]))
    def minute(day, clock):
        hour, value = map(int, clock.split(":"))
        return day * 1440 + hour * 60 + value
    current = local.weekday() * 1440 + local.hour * 60 + local.minute
    start = minute(config["weekend_start_day"], config["weekend_start_time"])
    end = minute(config["weekend_end_day"], config["weekend_end_time"])
    return start <= current < end if start < end else current >= start or current < end


def automatic_break(now, config):
    return config["weekend_pause"] and inside_weekly_window(now, config)


def require_active(game):
    if game["status"] == "paused":
        raise ValueError("本实例已暂停，管理员恢复后才能使用交易工具")


async def run_automatic(plugin, gid, operation):
    import asyncio
    tasks = getattr(plugin, "automatic_tasks", None)
    if tasks is None:
        tasks = plugin.automatic_tasks = {}
    task = asyncio.ensure_future(operation)
    group = tasks.setdefault(gid, set())
    group.add(task)
    try:
        if plugin.engine.get(gid)["status"] == "paused":
            task.cancel()
        return await task
    except asyncio.CancelledError:
        if not asyncio.current_task().cancelling() and plugin.engine.get(gid)["status"] == "paused":
            raise ValueError("实例已暂停，自动任务已停止") from None
        raise
    finally:
        group.discard(task)
        if not group:
            tasks.pop(gid, None)


def status(values, now=None):
    import time
    from ..agent.decision_settings import settings
    now = time.time() if now is None else now
    return dict(market_closed=inside_weekly_window(now, WEEKEND),
                automatic_break=automatic_break(now, settings(values)))
