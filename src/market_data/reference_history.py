"""Daily reference rates, kept separate from executable quotes and OHLC."""

import asyncio
import json
import time
from datetime import datetime, timezone
from ..core.engine import dump, number, PAIRS
from .history import aggregate, identity
from .config import ENDPOINTS


class ReferenceHistory:
    def __init__(self, engine, market):
        self.engine, self.market = engine, market
        self.locks = {}
        self.gate = asyncio.Semaphore(2)
        engine.db.executescript("""
        CREATE TABLE IF NOT EXISTS reference_rates(pair TEXT,t INTEGER,data TEXT,PRIMARY KEY(pair,t));
        CREATE TABLE IF NOT EXISTS reference_ranges(pair TEXT,start INTEGER,end INTEGER,checked REAL,PRIMARY KEY(pair,start,end));
        """)

    async def page(self, settings, pair, period, before, limit):
        if pair not in PAIRS or period not in ("1d", "1w", "1M"):
            raise ValueError(
                "Frankfurter仅提供每日参考汇率；分钟K线请选择“实时行情源历史”。"
            )
        if (
            type(before) is not int
            or not 0 <= before <= time.time() + 86400
            or type(limit) is not int
            or not 10 <= limit <= 500
        ):
            raise ValueError("历史分页参数无效")
        async with self.locks.setdefault(pair, asyncio.Lock()):
            today = int(
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            end = min(today, before - 1) if before else today
            end = end // 86400 * 86400
            floor = int(datetime(1948, 1, 1, tzinfo=timezone.utc).timestamp())
            start = max(floor, end - 730 * 86400)
            if end < floor:
                return self.result(settings, pair, period, [], False, "")
            if before:
                covered = self.engine.db.execute(
                    "SELECT checked,end FROM reference_ranges WHERE pair=? AND start<=? AND end>=? ORDER BY checked DESC LIMIT 1",
                    (pair, start, end),
                ).fetchone()
            else:
                covered = self.engine.db.execute(
                    "SELECT checked,end FROM reference_ranges WHERE pair=? AND start<=? AND end>=? ORDER BY end DESC LIMIT 1",
                    (pair, start, start),
                ).fetchone()
            need = not covered or (
                not before and (covered[1] < end or time.time() - covered[0] > 3600)
            )
            warning = ""
            if need:
                request_start = start
                if covered and not before:
                    latest = self.engine.db.execute(
                        "SELECT MAX(t) FROM reference_rates WHERE pair=?", (pair,)
                    ).fetchone()[0]
                    if latest is not None:
                        request_start = max(
                            start, latest
                        )  # Recheck only newest published date and newer dates.

                def dates(stamp):
                    return datetime.fromtimestamp(stamp, timezone.utc).strftime(
                        "%Y-%m-%d"
                    )

                try:
                    async with self.gate:
                        raw = await self.market.fetch(
                            ENDPOINTS["frankfurter_rates"],
                            {
                                "base": pair[:3],
                                "quotes": pair[4:],
                                "from": dates(request_start),
                                "to": dates(end),
                            },
                        )
                    rows = json.loads(raw)
                    if not isinstance(rows, list):
                        raise ValueError("Frankfurter历史数据格式异常")
                    parsed = []
                    for row in rows:
                        if (
                            row.get("base", "").upper() != pair[:3]
                            or row.get("quote", "").upper() != pair[4:]
                        ):
                            continue
                        stamp = int(
                            datetime.strptime(row["date"], "%Y-%m-%d")
                            .replace(tzinfo=timezone.utc)
                            .timestamp()
                        )
                        rate = number(row["rate"])
                        if rate <= 0 or not request_start <= stamp <= end:
                            continue
                        # Scalar daily observation; these fields are only a shared transport shape, never intraday OHLC.
                        parsed.append(
                            dict(
                                time=stamp,
                                open=float(rate),
                                high=float(rate),
                                low=float(rate),
                                close=float(rate),
                            )
                        )
                    with self.engine.transaction():
                        for bar in parsed:
                            self.engine.db.execute(
                                "INSERT OR REPLACE INTO reference_rates VALUES(?,?,?)",
                                (pair, bar["time"], dump(bar)),
                            )
                        self.engine.db.execute(
                            "INSERT OR REPLACE INTO reference_ranges VALUES(?,?,?,?)",
                            (pair, start, end, time.time()),
                        )
                except Exception as exc:
                    warning = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "参考汇率更新失败，显示本地已保存数据。"
                    )
                    if not self.engine.db.execute(
                        "SELECT 1 FROM reference_rates WHERE pair=? AND t<=? LIMIT 1",
                        (pair, end),
                    ).fetchone():
                        raise ValueError(warning) from None
            rows = self.engine.db.execute(
                "SELECT data FROM reference_rates WHERE pair=? AND t<=? ORDER BY t",
                (pair, end),
            ).fetchall()
            bars = [json.loads(r[0]) for r in rows]
            if period != "1d":
                # Weekly/monthly view uses the last published reference for each calendar bucket.
                bars = aggregate(bars, period, "frankfurter")
                bars = [
                    dict(
                        time=b["time"],
                        open=b["close"],
                        high=b["close"],
                        low=b["close"],
                        close=b["close"],
                    )
                    for b in bars
                ]
            bars = [b for b in bars if not before or b["time"] < before]
            selected = bars[-limit:]
            more = bool(selected) and (len(bars) > limit or start > floor)
            return self.result(settings, pair, period, selected, more, warning)

    def result(self, settings, pair, period, bars, more, warning):
        return dict(
            feed=identity(settings),
            pair=pair,
            period=period,
            source="frankfurter",
            reference=True,
            bars=bars,
            has_more=more,
            next_before=bars[0]["time"] if bars and more else None,
            warning=warning,
            retention="Frankfurter每日参考汇率；周/月显示该周期最后一次参考价，不是盘中OHLC，不参与成交。",
        )
