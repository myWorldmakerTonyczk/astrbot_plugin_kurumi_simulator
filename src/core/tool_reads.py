"""Compact market and diary projections for model-facing tools."""

from ..market_data.history import PERIODS
from .engine import PAIRS

MARKET_DETAIL = dict(type="boolean", description="需要完整计划和账户配置时才开启，默认false")
HISTORY_FIELDS = dict(
    pair=dict(type="string", description="货币对，例如EUR/USD"),
    period=dict(type="string", enum=list(PERIODS)),
    limit=dict(type="integer", minimum=10, maximum=200, description="每页K线数量，默认20"),
    pages=dict(type="integer", minimum=1, maximum=5, description="连续页数，合计最多200根"),
    before=dict(type="integer", minimum=0, description="查更早行情时传上一页的next_before"),
    include_bars=dict(type="boolean", description="开启时返回全部K线，默认只展示最近8根和区间摘要"),
)
DIARY_FIELDS = dict(
    before=dict(type="string", description="日期上界（YYYY-MM-DD，不含当天），翻页可传next_before"),
    limit=dict(type="integer", minimum=1, maximum=10, description="每页条数，默认3"),
    pages=dict(type="integer", minimum=1, maximum=5, description="连续页数，合计最多20条"),
    include_text=dict(type="boolean", description="开启时返回完整正文，默认每篇只返回开头160字"),
)


async def history_view(plugin, *, pair="", period="1h", limit=20, pages=1, before=0, include_bars=False):
    if (pair not in PAIRS or type(limit) is not int or not 10 <= limit <= 200
            or type(pages) is not int or not 1 <= pages <= 5 or pages * limit > 200
            or type(include_bars) is not bool):
        raise ValueError("历史行情参数无效，每次最多200根K线")
    data = await plugin.history.page(
        dict(plugin.settings(), history_source="market"), pair, period, before, limit * pages
    )
    bars = data["bars"]
    result = dict(pair=pair, period=period, source=data.get("source"), next_before=data.get("next_before"),
                  has_more=data.get("has_more", False), warning=data.get("warning", ""))
    result["count"] = len(bars)
    if bars:
        result["range"] = dict(
            start=bars[0]["time"], end=bars[-1]["time"], open=bars[0]["open"],
            close=bars[-1]["close"], high=max(row["high"] for row in bars),
            low=min(row["low"] for row in bars),
        )
    columns = ("time", "open", "high", "low", "close")
    result["columns"] = columns
    result["bars"] = [[row[key] for key in columns] for row in (bars if include_bars else bars[-8:])]
    return result


def diary_view(store, gid, *, before="", limit=3, pages=1, include_text=False):
    if (not isinstance(before, str) or type(limit) is not int or not 1 <= limit <= 10
            or type(pages) is not int or not 1 <= pages <= 5 or pages * limit > 20
            or type(include_text) is not bool):
        raise ValueError("日记分页参数无效，每次最多20篇")
    count = limit * pages
    rows = store.list(gid, before, count + 1, successful_only=True)
    entries = []
    for row in rows[:count]:
        content = row["content"]
        entries.append(dict(day=row["day"], content=content if include_text or len(content) <= 160 else content[:160] + "…"))
    return dict(entries=entries, next_before=entries[-1]["day"] if len(rows) > count else None)
