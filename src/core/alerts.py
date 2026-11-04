"""Authenticated-dashboard notification projection from the immutable journal."""

import json
from .engine import number


def notices(engine, gid, after=None, limit=100):
    engine.get(gid)
    if after is None:
        cursor = engine.db.execute(
            "SELECT COALESCE(MAX(seq),0) FROM logs WHERE game=?", (gid,)
        ).fetchone()[0]
        return dict(cursor=cursor, events=[], has_more=False)
    if type(after) is not int or not 0 <= after < 2**63:
        raise ValueError("提醒游标无效")
    rows = engine.db.execute(
        "SELECT seq,data FROM logs WHERE game=? AND seq>? ORDER BY seq LIMIT ?",
        (gid, after, limit + 1),
    ).fetchall()
    events = []
    for seq, raw in rows[:limit]:
        event = json.loads(raw)
        detail = event.get("detail", {})
        action = event["action"]

        def money(value):
            return f"{number(value):,.2f}"

        title = body = ""
        level = "info"
        if event.get("status") == "rejected":
            title = "操作失败"
            body = detail.get("error") or event.get("reason") or "操作未执行"
            level = "danger"
        elif action == "deposit":
            title = "虚拟资金已追加"
            body = f"追加 ${money(detail['amount'])}，可用于保证金，不计入盈利。"
            level = "success"
        elif action in ("borrow", "repay"):
            title = "已借入虚拟资金" if action == "borrow" else "虚拟贷款已偿还"
            body = f"本次 ${money(detail['amount'])}；待还贷款 ${money(detail.get('debt', 0))}。"
            level = "success"
        elif action == "margin_call":
            title = "保证金不足提醒"
            body = f"保证金水平 {number(detail['level']):.2f}%，可追加虚拟资金或减少持仓。低于50%会触发模拟强平。"
            level = "warning"
        elif action == "close" and (
            detail.get("kind") == "liquidation" or "强平" in event.get("reason", "")
        ):
            position = detail.get("position", {})
            title = "模拟强平 / 爆仓提醒"
            body = f"{position.get('pair', '')} 持仓已被系统强制平仓。\n{event.get('reason', '')}\n本笔盈亏 ${money(position.get('pnl', 0))}；平仓费 ${money(detail.get('fee', 0))}。"
            level = "danger"
        elif action == "end":
            title = (
                "爆仓，本局结束"
                if detail.get("bankrupt")
                else "本局结束：" + detail.get("outcome", "已结束")
            )
            body = (
                "净值已耗尽，剩余持仓已结算。"
                if detail.get("bankrupt")
                else "已触发游戏结束条件，详情请查看交易日志。"
            )
            level = "danger" if detail.get("outcome") == "失败" else "info"
        if title:
            events.append(
                dict(
                    id=seq,
                    title=title,
                    body=body,
                    level=level,
                    request_id=detail.get("request_id"),
                    action=action,
                )
            )
    return dict(
        cursor=rows[min(len(rows), limit) - 1][0] if rows else after,
        events=events,
        has_more=len(rows) > limit,
    )
