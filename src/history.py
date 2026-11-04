"""Persistent six-pair OHLC capture and backwards provider pagination."""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from .engine import PAIRS, dump, number
from .market import endpoint, signature, source

PERIODS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    "1M": 2592000,
}
GRANULARITY = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}


def identity(settings):
    key = (
        "frankfurter-v2"
        if settings.get("history_source") == "frankfurter"
        else signature(settings)
    )
    return hashlib.sha256(dump(key).encode()).hexdigest()[:24]


def bucket(stamp, period, provider="biquote"):
    if period not in ("1d", "1w", "1M"):
        return int(stamp) // PERIODS[period] * PERIODS[period]
    zone = timezone(timedelta(hours=8)) if provider == "sina" else timezone.utc
    dt = datetime.fromtimestamp(stamp, zone).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if period == "1w":
        dt -= timedelta(days=dt.weekday())
    if period == "1M":
        dt = dt.replace(day=1)
    return int(dt.timestamp())


def period_end(start, period, provider):
    if period != "1M":
        return start + PERIODS[period]
    zone = timezone(timedelta(hours=8)) if provider == "sina" else timezone.utc
    dt = datetime.fromtimestamp(start, zone)
    dt = dt.replace(year=dt.year + (dt.month == 12), month=dt.month % 12 + 1, day=1)
    return int(dt.timestamp())


def aggregate(bars, period, provider):
    result = {}
    for bar in sorted(bars, key=lambda b: b["time"]):
        t = bucket(bar["time"], period, provider)
        if t not in result:
            result[t] = dict(bar, time=t)
        else:
            target = result[t]
            target.update(
                high=max(target["high"], bar["high"]),
                low=min(target["low"], bar["low"]),
                close=bar["close"],
            )
    return list(result.values())


def timestamp(value, china=False):
    if china:
        return int(
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone(timedelta(hours=8)))
            .timestamp()
        )
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("K线时间缺少时区")
    return int(dt.timestamp())


def clean_bar(t, opening, high, low, close):
    values = [number(v) for v in (opening, high, low, close)]
    opening, high, low, close = values
    if (
        min(values) <= 0
        or high < max(opening, close, low)
        or low > min(opening, close, high)
        or t <= 0
        or t > time.time() + 5
    ):
        raise ValueError("K线数据无效")
    return dict(
        time=int(t),
        open=float(opening),
        high=float(high),
        low=float(low),
        close=float(close),
    )


def parse_bars(provider, raw):
    if provider == "sina":
        text = raw.decode("utf-8", errors="replace")
        # Accept only a JSON array inside the fixed callback. Never execute JavaScript.
        start = text.find("kurumi(")
        end = text.rfind(");")
        if start < 0 or end < start:
            raise ValueError("新浪历史行情格式无效")
        rows = json.loads(text[start + 7 : end])
        if isinstance(rows, str):
            parsed = []
            for line in rows.split("|"):
                fields = line.split(",")
                if len(fields) >= 5:
                    parsed.append(
                        dict(
                            d=fields[0] + " 00:00:00",
                            o=fields[1],
                            l=fields[2],
                            h=fields[3],
                            c=fields[4],
                        )
                    )
            rows = parsed
    else:
        body = json.loads(raw)
        rows = (
            body.get("bars", []) if provider == "biquote" else body.get("candles", [])
        )
    result = {}
    for row in rows:
        try:
            if provider == "sina":
                t = timestamp(row["d"], True)
                bar = clean_bar(t, row["o"], row["h"], row["l"], row["c"])
            elif provider == "biquote":
                t = timestamp(row["openTime"])
                bar = clean_bar(t, row["open"], row["high"], row["low"], row["close"])
            else:
                t = timestamp(row["time"])
                bar = clean_bar(t, *(row["mid"][k] for k in ("o", "h", "l", "c")))
            result[t] = bar
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
    return sorted(result.values(), key=lambda b: b["time"])


class History:
    def __init__(self, engine, market):
        self.engine, self.market = engine, market
        from .reference_history import ReferenceHistory

        self.reference = ReferenceHistory(engine, market)
        self.gate = asyncio.Semaphore(2)
        self.locks = {}
        self.loaded = {}
        engine.db.execute(
            "CREATE TABLE IF NOT EXISTS history_pages(feed TEXT,pair TEXT,period TEXT,before INTEGER,lim INTEGER,PRIMARY KEY(feed,pair,period,before,lim))"
        )
        self.remote_more = {}
        engine.db.execute(
            "CREATE TABLE IF NOT EXISTS history_refresh(feed TEXT,pair TEXT,period TEXT,last_t INTEGER,PRIMARY KEY(feed,pair,period))"
        )
        engine.db.execute("""CREATE TABLE IF NOT EXISTS candles(
            feed TEXT,pair TEXT,period TEXT,t INTEGER,data TEXT,last_tick REAL,
            PRIMARY KEY(feed,pair,period,t))""")

    def record(self, settings):
        feed = identity(dict(settings, history_source="market"))
        now = time.time()
        with self.engine.transaction():
            for pair in PAIRS:
                q = self.engine.quotes.get(pair)
                if not q or not q["tradeable"] or now - q["timestamp"] > 30:
                    continue
                stamp = q["timestamp"]
                mid = (number(q["bid"]) + number(q["ask"])) / 2
                for period, seconds in PERIODS.items():
                    t = bucket(stamp, period, source(settings))
                    row = self.engine.db.execute(
                        "SELECT data,last_tick FROM candles WHERE feed=? AND pair=? AND period=? AND t=?",
                        (feed, pair, period, t),
                    ).fetchone()
                    if row and stamp <= row[1]:
                        continue
                    bar = (
                        json.loads(row[0]) if row else clean_bar(t, mid, mid, mid, mid)
                    )
                    bar.update(
                        high=max(bar["high"], float(mid)),
                        low=min(bar["low"], float(mid)),
                        close=float(mid),
                    )
                    self.engine.db.execute(
                        "INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?)",
                        (feed, pair, period, t, dump(bar), stamp),
                    )

    def cached(self, feed, pair, period, before, limit):
        rows = self.engine.db.execute(
            "SELECT data FROM candles WHERE feed=? AND pair=? AND period=? AND t<? ORDER BY t DESC LIMIT ?",
            (feed, pair, period, before or 2**62, limit),
        ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    async def remote(self, settings, pair, period, before, limit):
        provider = source(settings)
        checkpoint = (
            None
            if before
            else self.engine.db.execute(
                "SELECT last_t FROM history_refresh WHERE feed=? AND pair=? AND period=?",
                (identity(settings), pair, period),
            ).fetchone()
        )
        since = checkpoint[0] if checkpoint else 0
        if provider == "biquote":
            base = urlsplit(endpoint(settings, "biquote"))
            if not base.path.rstrip("/").endswith("/latest"):
                raise ValueError(
                    "自定义 biquote 地址需以 /latest 结尾，才能推导历史接口"
                )
            url = urlunsplit(
                (
                    base.scheme,
                    base.netloc,
                    base.path.rstrip("/")[:-6] + pair.replace("/", "") + "/ohlc",
                    "",
                    "",
                )
            )
            params = {
                "interval": "1d" if period in ("1w", "1M") else period,
                "limit": 1000 if period in ("1w", "1M") else limit + 1,
            }
            if since:
                params["from"] = datetime.fromtimestamp(since, timezone.utc).isoformat()
            if before:
                params["to"] = datetime.fromtimestamp(
                    before - 1, timezone.utc
                ).isoformat()
            raw = await self.market.fetch(url, params)
        elif provider == "sina":
            if period in ("1d", "1w", "1M"):
                raw = await self.market.fetch(
                    "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/kurumi/NewForexService.getDayKLine",
                    {"symbol": "fx_s" + pair.replace("/", "").lower()},
                    {"Referer": "https://finance.sina.com.cn/"},
                )
            else:
                count = (
                    min(5000, max(3, int((time.time() - since) / PERIODS[period]) + 3))
                    if since
                    else limit + 1
                )
                if before:
                    count += self.engine.db.execute(
                        "SELECT count(*) FROM candles WHERE feed=? AND pair=? AND period=? AND t>=?",
                        (identity(settings), pair, period, before),
                    ).fetchone()[0]
                raw = await self.market.fetch(
                    "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/kurumi/NewForexService.getMinKline",
                    {
                        "symbol": "fx_s" + pair.replace("/", "").lower(),
                        "scale": PERIODS[period] // 60,
                        "datalen": min(5000, count),
                    },
                    {"Referer": "https://finance.sina.com.cn/"},
                )
        else:
            token, account = (
                settings.get("market_key", ""),
                settings.get("market_account", ""),
            )
            if (
                not token
                or not account
                or not all(c.isdigit() or c == "-" for c in account)
            ):
                raise ValueError("OANDA历史行情需要有效模拟账户与令牌")
            params = {
                "price": "M",
                "granularity": GRANULARITY[period],
                "count": limit + 1,
                "alignmentTimezone": "UTC",
                "dailyAlignment": 0,
                "weeklyAlignment": "Monday",
            }
            if before:
                params["to"] = datetime.fromtimestamp(
                    before - 1, timezone.utc
                ).isoformat()
            if since:
                params.pop("count", None)
                params["from"] = datetime.fromtimestamp(since, timezone.utc).isoformat()
            raw = await self.market.fetch(
                f"https://api-fxpractice.oanda.com/v3/accounts/{account}/instruments/{pair.replace('/', '_')}/candles",
                params,
                {"Authorization": "Bearer " + token},
            )
        bars = parse_bars(provider, raw)
        truncated_daily = (
            provider == "biquote" and period in ("1w", "1M") and len(bars) >= 1000
        )
        self.remote_more[(identity(settings), pair, period, before)] = truncated_daily
        if period in ("1w", "1M") and provider != "oanda":
            bars = aggregate(bars, period, provider)
            if truncated_daily and len(bars) > 1:
                bars = bars[1:]  # Do not publish an incomplete leading week/month.

        if before:
            bars = [b for b in bars if b["time"] < before]
        return bars

    async def page(self, settings, pair, period="5m", before=0, limit=200):
        if settings.get("history_source") == "frankfurter":
            return await self.reference.page(settings, pair, period, before, limit)
        if pair not in PAIRS or period not in PERIODS:
            raise ValueError("货币对或K线周期无效")
        if (
            type(before) is not int
            or before < 0
            or before > int(time.time()) + 86400
            or type(limit) is not int
            or not 10 <= limit <= 500
        ):
            raise ValueError("历史分页参数无效")
        feed = identity(settings)
        key = (feed, pair, period, before, limit)
        async with self.locks.setdefault(key, asyncio.Lock()):
            bars = self.cached(feed, pair, period, before, limit + 1)
            error = ""
            complete = (
                before
                and self.engine.db.execute(
                    "SELECT 1 FROM history_pages WHERE feed=? AND pair=? AND period=? AND before=? AND lim=?",
                    key,
                ).fetchone()
            )
            if (
                not complete
                and (len(bars) < limit + 1 or not before)
                and time.monotonic() - self.loaded.get(key, -1000) > 30
            ):
                try:
                    started = time.time()
                    async with self.gate:
                        remote = await self.remote(
                            settings, pair, period, before, limit
                        )
                    with self.engine.transaction():
                        for bar in remote:
                            old = self.engine.db.execute(
                                "SELECT data,last_tick FROM candles WHERE feed=? AND pair=? AND period=? AND t=?",
                                (feed, pair, period, bar["time"]),
                            ).fetchone()
                            # Keep newer sampled close/extremes if the fetch crossed a live quote update.
                            last_tick = min(
                                started,
                                period_end(bar["time"], period, source(settings)) - 1,
                            )
                            if old and old[1] > started:
                                prior = json.loads(old[0])
                                bar = dict(
                                    bar,
                                    high=max(bar["high"], prior["high"]),
                                    low=min(bar["low"], prior["low"]),
                                    close=prior["close"],
                                )
                                last_tick = old[1]
                            self.engine.db.execute(
                                "INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?)",
                                (feed, pair, period, bar["time"], dump(bar), last_tick),
                            )
                    if not before and remote:
                        self.engine.db.execute(
                            "INSERT OR REPLACE INTO history_refresh VALUES(?,?,?,?)",
                            (feed, pair, period, max(b["time"] for b in remote)),
                        )
                    if before:
                        self.engine.db.execute(
                            "INSERT OR IGNORE INTO history_pages VALUES(?,?,?,?,?)", key
                        )
                    self.loaded[key] = time.monotonic()
                    bars = self.cached(feed, pair, period, before, limit + 1)
                except Exception as exc:
                    error = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "历史行情获取失败，请稍后重试"
                    )
                    if not bars:
                        raise ValueError(error) from None
            has_more = len(bars) > limit or self.remote_more.get(
                (feed, pair, period, before), False
            )
            # A full page can still have older provider data; try once at the next cursor.
            if len(bars) == limit:
                has_more = True
            selected = bars[-limit:]
            return dict(
                feed=feed,
                pair=pair,
                period=period,
                source=source(settings),
                bars=selected,
                next_before=selected[0]["time"] if selected and has_more else None,
                has_more=has_more,
                warning=error,
                retention="上游历史范围有限；已获取和六品种实时采样均保存在本地。",
            )
