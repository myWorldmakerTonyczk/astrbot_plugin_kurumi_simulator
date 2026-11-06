"""Shared scoped operations for chat tools and silent scheduled agents."""

import asyncio
from .engine import PAIRS
from .journal import compact_log, journal

RECORD_VOICE = (
    "用户没有额外要求时，报告、看盘摘要、交易理由、日志和计划默认沿用原人设的语气，"
    "自然表达即可，不用刻意严肃或正式。用户指定了口吻或格式时按用户要求。"
    "价格、数量、触发条件和成交结果写准确。"
)

WRITE_ACTIONS = {"open", "close", "protect", "observe", "plan", "borrow", "repay"}


def lock_for(plugin, gid):
    return plugin.instance_locks.setdefault(gid, asyncio.Lock())


def public_snapshot(plugin, gid, log_limit=30):
    if type(log_limit) is not int or not 0 <= log_limit <= 50:
        raise ValueError("近期日志条数须在0到50之间")
    result = plugin.engine.snapshot(gid, log_limit)
    result["logs"] = [compact_log(entry) for entry in result["logs"]]
    result["game"] = dict(result["game"])
    result["game"].pop("user_binding", None)
    from ..users.policy import effective

    result["game"]["interval"] = effective(plugin.engine, result["game"])["effective_interval"]
    result["quotes"] = {p: q for p, q in result["quotes"].items() if p in PAIRS}
    return result


async def execute(plugin, gid, action, body, *, already_locked=False):
    if action == "state":
        return public_snapshot(plugin, gid, body.get("log_limit", 30))
    plugin.engine.get(gid)
    if action == "logs":
        return journal(plugin.engine, gid, **body)
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
        result = plugin.engine.action(gid, action, body, "ai")
        # The synchronous action appends its audit entry before returning.
        entry = plugin.engine.logs(gid, limit=1)[0]
        receipt = dict(action=action, revision=result["revision"], log_id=entry["id"])
        if action not in {"plan", "observe"}:
            receipt.update(balance=entry["balance"], detail=entry["detail"])
        return receipt

    if already_locked:
        return commit()
    async with lock:
        return commit()
