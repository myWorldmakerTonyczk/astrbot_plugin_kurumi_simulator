"""Shared scoped operations for chat tools and silent scheduled agents."""

import asyncio
from .engine import PAIRS

WRITE_ACTIONS = {"open", "close", "protect", "observe", "plan", "borrow", "repay"}


def lock_for(plugin, gid):
    return plugin.instance_locks.setdefault(gid, asyncio.Lock())


def public_snapshot(plugin, gid):
    result = plugin.engine.snapshot(gid)
    result["game"] = dict(result["game"])
    result["game"].pop("user_binding", None)
    from ..users.policy import effective

    result["game"]["interval"] = effective(plugin.engine, result["game"])["effective_interval"]
    result["quotes"] = {p: q for p, q in result["quotes"].items() if p in PAIRS}
    return result


async def execute(plugin, gid, action, body, *, already_locked=False):
    if action == "state":
        return public_snapshot(plugin, gid)
    plugin.engine.get(gid)
    if action == "logs":
        before = body.get("before", 0)
        limit = body.get("limit", 20)
        pair = body.get("pair", "")
        if (
            type(before) is not int
            or before < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
            or pair
            and pair not in PAIRS
        ):
            raise ValueError("日志分页参数无效")
        return plugin.engine.logs(gid, before or 2**63 - 1, limit, pair)
    if action == "history":
        pair = body.get("pair", "")
        period = body.get("period", "1h")
        limit = body.get("limit", 80)
        before = body.get("before", 0)
        if pair not in PAIRS or type(limit) is not int or not 10 <= limit <= 200:
            raise ValueError("历史行情参数无效")
        return await plugin.history.page(
            dict(plugin.settings(), history_source="market"),
            pair,
            period,
            before,
            limit,
        )
    if action not in WRITE_ACTIONS:
        raise ValueError("无此操作权限；不能自行充值、改规则或修改笔记")
    if not str(body.get("reason", "")).strip():
        raise ValueError("请填写简短操作理由概要")
    if action == "plan" and (
        not isinstance(body.get("text"), str)
        or not body["text"].strip()
        or len(body["text"]) > 6000
    ):
        raise ValueError("计划须为1～6000字符")
    lock = lock_for(plugin, gid)
    if not already_locked and lock.locked():
        raise ValueError("本实例正在后台看盘，请稍后再操作；可以先查询状态")

    def commit():
        plugin.engine.action(gid, action, body, "ai")
        return public_snapshot(plugin, gid)

    if already_locked:
        return commit()
    async with lock:
        return commit()
