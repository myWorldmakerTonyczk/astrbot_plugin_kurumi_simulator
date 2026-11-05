"""Account sampling and scoped projections for review surfaces."""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..diary.store import redact
from ..market_data.history import bucket
from ..market_data.market import source

PERIOD_BY_DAYS = {1: "15m", 7: "1h", 30: "4h"}


def _ledger_event(seq, item, pair, period, provider):
    detail = item.get("detail") or {}
    position = detail.get("position") or {}
    action, actor, status = item["action"], item["source"], item["status"]
    if action not in {"open", "close", "protect", "plan", "observe", "analysis", "margin_call", "end"}:
        return None
    instrument = position.get("pair")
    if instrument and instrument != pair:
        return None
    price = position.get("entry") if action == "open" else position.get("current")
    return dict(
        id=f"log-{seq}", job=item.get("decision_id"), time=item["created"],
        bar=bucket(item["created"], period, provider), action=action, actor=actor,
        status=status, reason=redact(item.get("reason", "")),
        text=redact(detail.get("summary") or detail.get("text") or detail.get("error") or ""),
        position={k: position[k] for k in ("id", "pair", "side", "units", "sl", "tp", "entry", "created", "pnl") if k in position},
        price=float(price) if price and status == "success" and action in {"open", "close"} else None,
        fee=float(detail.get("fee") or 0),
        kind=detail.get("kind", ""),
    )


def _compact_marks(rows):
    if len(rows) <= 1200:
        return rows
    step = (len(rows) + 599) // 600
    selected = []
    for i in range(0, len(rows), step):
        group = rows[i:i + step]
        worst = max(range(len(group)), key=lambda j: group[j]["drawdown"])
        selected.extend(i + j for j in sorted({worst, len(group) - 1}))
    return [rows[i] for i in selected]


async def review(plugin, gid, pair="", days=1, end=0, *, private=True, include_candles=True):
    game = plugin.engine.get(gid)
    db = plugin.engine.db
    now = time.time()
    if type(end) is not int or not 0 <= end <= now:
        raise ValueError("复盘结束时间无效")
    before = end + 1 if end else 0
    if type(days) is not int or days not in PERIOD_BY_DAYS:
        raise ValueError("请选择 1、7 或 30 天")
    end = end or now
    start = end - days * 86400
    totals = db.execute(
        """SELECT json_extract(data,'$.detail.position.pair') AS pair, count(*) AS fills,
                  sum(coalesce(CAST(json_extract(data,'$.detail.position.pnl') AS REAL),0)
                      - coalesce(CAST(json_extract(data,'$.detail.fee') AS REAL),0)) AS net
           FROM logs WHERE game=? AND created BETWEEN ? AND ?
           AND json_extract(data,'$.status')='success'
           AND json_extract(data,'$.action') IN ('open','close')
           GROUP BY pair ORDER BY fills DESC, max(seq) DESC""",
        (gid, start, end),
    )
    pair_stats = {row["pair"]: dict(row) for row in totals if row["pair"] in game["pairs"]}
    for instrument in game["pairs"]:
        pair_stats.setdefault(instrument, dict(pair=instrument, fills=0, net=0))
    if not pair:
        pair = next(iter(pair_stats))
    if pair not in game["pairs"]:
        raise ValueError("请选择实例内的品种")
    period = PERIOD_BY_DAYS[days]
    settings = dict(plugin.settings(), history_source="market")
    provider = source(settings)
    history = {"bars": [], "warning": ""}
    if include_candles:
        history = await plugin.history.page(settings, pair, period, before, 200)
    rows = db.execute(
        """SELECT seq,data FROM logs WHERE game=? AND created>=? AND created<=?
           AND json_extract(data,'$.action') IN ('open','close','protect','plan','observe','analysis','margin_call','end')
           ORDER BY created DESC,seq DESC LIMIT 501""", (gid, start, end)
    ).fetchall()
    events = [
        event for seq, raw in reversed(rows[:500])
        if (event := _ledger_event(seq, json.loads(raw), pair, period, provider)) is not None
    ]
    jobs = db.execute(
        """SELECT id,trigger,state,created,updated,result,error,events FROM decision_jobs
           WHERE game=? AND created>=? AND created<=? ORDER BY created DESC,id DESC LIMIT 301""",
        (gid, start, end),
    ).fetchall()
    for jid, trigger, status, created, updated, result, error, risks in jobs[:300]:
        operations = [item for item in events if item["job"] == jid]
        if status in {"success", "failed"} and updated > end:
            status, result, error = "running", "", ""
        completed = json.loads(result) if result else {}
        outcome = ""
        if status == "success":
            calls = set(completed.get("tool_calls") or ())
            actions = calls | {e["action"] for e in operations if e["status"] == "success"}
            if actions & {"open", "close"}:
                outcome = "已成交"
            elif "observe" in actions:
                outcome = "已记录观望"
            elif any(e["status"] == "rejected" for e in operations):
                outcome = "操作未执行"
            elif "tool_calls" in completed:
                outcome = "已完成，未成交"
        summary = completed.get("summary", "")
        events.append(dict(
            id=f"job-{jid}", job=jid, time=created, bar=bucket(created, period, provider),
            action="review", actor="ai", status=status, reason=trigger,
            text=redact(error or summary), outcome=outcome,
            related=[f"log-{x['id']}" for x in json.loads(risks) if "id" in x],
        ))
    baseline = db.execute(
        """SELECT json_extract(data,'$.detail.text') FROM logs WHERE game=? AND created<?
           AND json_extract(data,'$.action')='plan' AND json_extract(data,'$.status')='success'
           ORDER BY created DESC,seq DESC LIMIT 1""", (gid, start)
    ).fetchone()
    marks = [dict(row) for row in db.execute(
        "SELECT t AS time,equity,return_rate,drawdown FROM replay_equity WHERE game=? AND t BETWEEN ? AND ? ORDER BY t",
        (gid, start, end),
    )]
    diaries = []
    if private:
        diaries = [
            {key: row[key] for key in ("day", "zone", "content")}
            for row in db.execute(
                """SELECT day,zone,content FROM diaries WHERE game=? AND status='success'
                   AND start<=? AND end>? ORDER BY day DESC LIMIT 31""", (gid, end, start)
            )
        ]
        for diary in diaries:
            diary["content"] = redact(diary["content"])
    else:
        events = [event for event in events if event["action"] in {"open", "close"} and event["status"] == "success"]
        for event in events:
            event.update(reason="", text="", job=None)
            event["position"].pop("sl", None)
            event["position"].pop("tp", None)
    return dict(
        private=private, name=redact(game["name"]) if private else "虚拟交易复盘", pair=pair,
        pairs=game["pairs"], pair_stats=list(pair_stats.values()), period=period, days=days, start=start, end=end,
        candles=[bar for bar in history["bars"] if start <= bar["time"] <= end],
        warning=history.get("warning", ""), events=sorted(events, key=lambda item: item["time"]),
        baseline=redact(baseline[0]) if private and baseline and baseline[0] else "",
        marks=_compact_marks(marks), diaries=diaries,
        truncated=len(rows) > 500 or len(jobs) > 300,
        day=datetime.fromtimestamp(end, ZoneInfo("Asia/Shanghai")).date().isoformat(),
    )
