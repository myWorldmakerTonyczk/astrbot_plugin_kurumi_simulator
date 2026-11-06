"""Bounded journal views for chat and scheduled trading tools."""

import json

from .engine import PAIRS

LOG_LIMIT = dict(type="integer", minimum=0, maximum=50, description="近期交易日志条数，默认30，0表示省略")
JOURNAL_FIELDS = dict(
    pair=dict(type="string", description="按货币对筛选，留空查全部"),
    page=dict(type="integer", minimum=1, maximum=1000000, description="起始页，默认第1页"),
    page_size=dict(type="integer", minimum=1, maximum=50, description="每页条数，默认20"),
    pages=dict(type="integer", minimum=1, maximum=5, description="连续返回几页，合计最多100条"),
    sort=dict(type="string", enum=["newest", "oldest", "action"], description="最新优先（默认）、最早优先或按操作类型归组"),
    filter=dict(type="string", enum=["all", "operations", "fills", "rejected"], description="全部、仅实际操作（含保护线和资金变动）、仅成交或未执行"),
    source=dict(type="string", enum=["all", "ai", "human", "system"], description="按执行者筛选"),
    include_text=dict(type="boolean", description="是否附上完整计划和分析正文，默认只返回摘要"),
    before=dict(type="integer", minimum=0, description="可选日志ID上界，用于固定翻页范围"),
    limit=dict(type="integer", minimum=1, maximum=50, description="兼容旧调用，等同page_size"),
)


def compact_log(entry):
    detail = dict(entry["detail"])
    for key in ("text", "summary"):
        value = detail.get(key)
        if isinstance(value, str) and len(value) > 120:
            detail[key] = value[:120] + "…"
    if isinstance(detail.get("position"), dict):
        detail["position"] = {k: v for k, v in detail["position"].items() if k != "reason"}
    reason = entry["reason"]
    return dict(entry, detail=detail, reason=reason[:160] + "…" if len(reason) > 160 else reason)


def journal(engine, gid, *, pair="", page=1, page_size=20, pages=1,
            sort="newest", filter="all", source="all", include_text=False,
            before=0, limit=None):
    if limit is not None:
        page_size = limit
    if (type(page) is not int or not 1 <= page <= 1000000
            or type(page_size) is not int or not 1 <= page_size <= 50
            or type(pages) is not int or not 1 <= pages <= 5 or pages * page_size > 100
            or type(before) is not int or not 0 <= before < 2**63
            or pair and pair not in PAIRS or type(include_text) is not bool):
        raise ValueError("日志分页参数无效，每次最多100条")
    orders = {"newest": "created DESC, seq DESC", "oldest": "created ASC, seq ASC",
              "action": "action ASC, created DESC, seq DESC"}
    if sort not in orders or filter not in ("all", "operations", "fills", "rejected") or source not in ("all", "ai", "human", "system"):
        raise ValueError("日志排序或筛选无效")
    if not before:
        before = engine.db.execute("SELECT coalesce(max(seq),0)+1 FROM logs WHERE game=?", (gid,)).fetchone()[0]
    params = [gid, before]
    clauses = ["game=?", "seq<?"]
    if pair:
        clauses.append("json_extract(data,'$.detail.position.pair')=?")
        params.append(pair)
    if source != "all":
        clauses.append("json_extract(data,'$.source')=?")
        params.append(source)
    if filter == "rejected":
        clauses.append("json_extract(data,'$.status')='rejected'")
    elif filter != "all":
        clauses.append("json_extract(data,'$.status')='success'")
        actions = "'open','close'" if filter == "fills" else "'open','close','protect','deposit','borrow','repay','loan_config','update_pairs','pause','resume','end'"
        clauses.append(f"json_extract(data,'$.action') IN ({actions})")
    where = " AND ".join(clauses)
    rows = engine.db.execute(
        f"SELECT seq,data,json_extract(data,'$.action') AS action FROM logs WHERE {where} "
        f"ORDER BY {orders[sort]} LIMIT ? OFFSET ?",
        (*params, page_size * pages + 1, (page - 1) * page_size),
    ).fetchall()
    has_more = len(rows) > page_size * pages
    entries = [dict(id=row[0], **json.loads(row[1])) for row in rows[:page_size * pages]]
    if not include_text:
        entries = [compact_log(entry) for entry in entries]
    return dict(page=page, page_size=page_size, pages=pages, before=before,
                next_page=page + pages if has_more else None, logs=entries)
