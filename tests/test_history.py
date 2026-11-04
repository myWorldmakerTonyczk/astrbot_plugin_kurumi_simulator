import json
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.engine import Engine, PAIRS
from src.history import History, identity, parse_bars, bucket, aggregate


def bars(count=205, end=None, step=300):
    end = end or int(time.time()) // step * step
    return [
        dict(
            openTime=datetime.fromtimestamp(
                end - (count - i - 1) * step, timezone.utc
            ).isoformat(),
            open=1.12,
            high=1.125,
            low=1.115,
            close=1.121,
        )
        for i in range(count)
    ]


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = Engine(":memory:")
        self.market = SimpleNamespace(
            fetch=AsyncMock(return_value=json.dumps({"bars": bars()}).encode())
        )
        self.h = History(self.engine, self.market)

    async def asyncTearDown(self):
        self.engine.db.close()

    async def test_restart_latest_uses_incremental_cursor(self):
        await self.h.page({}, "EUR/USD")
        fresh = History(self.engine, self.market)
        await fresh.page({}, "EUR/USD")
        self.assertIn("from", self.market.fetch.call_args.args[1])

    async def test_downloaded_old_page_persists_even_when_short(self):
        before = int(time.time()) - 86400
        self.market.fetch.return_value = json.dumps(
            {"bars": bars(count=20, end=before - 300)}
        ).encode()
        await self.h.page({}, "EUR/USD", before=before)
        fresh = History(self.engine, self.market)
        await fresh.page({}, "EUR/USD", before=before)
        self.assertEqual(self.market.fetch.await_count, 1)

    async def test_initial_and_backwards_pages(self):
        first = await self.h.page({}, "EUR/USD")
        self.assertEqual(len(first["bars"]), 200)
        self.assertTrue(first["has_more"])
        cursor = first["next_before"]
        self.market.fetch.return_value = json.dumps(
            {"bars": bars(end=cursor - 300)}
        ).encode()
        older = await self.h.page({}, "EUR/USD", before=cursor)
        self.assertLess(older["bars"][-1]["time"], cursor)
        self.assertEqual(len(older["bars"]), 200)

    async def test_all_six_persist_without_view(self):
        for pair in PAIRS:
            self.engine.quotes[pair] = dict(
                bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
            )
        self.h.record({})
        feed = identity({})
        for pair in PAIRS:
            for period in ("1m", "5m", "1d", "1w", "1M"):
                self.assertEqual(len(self.h.cached(feed, pair, period, 0, 10)), 1)
        self.assertEqual(self.market.fetch.await_count, 0)

    async def test_repeated_ticks_no_duplicate(self):
        self.engine.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
        )
        self.h.record({})
        self.h.record({})
        self.assertEqual(len(self.h.cached(identity({}), "EUR/USD", "5m", 0, 10)), 1)

    async def test_no_source_mix(self):
        self.h.record({})
        await self.h.page({}, "EUR/USD")
        self.assertEqual(
            self.h.cached(identity({"market_source": "sina"}), "EUR/USD", "5m", 0, 200),
            [],
        )

    async def test_unsafe_or_unknown_query(self):
        for pair, period, before in [
            ("../../x", "5m", 0),
            ("EUR/USD", "bad", 0),
            ("EUR/USD", "5m", -1),
        ]:
            with self.assertRaises(ValueError):
                await self.h.page({}, pair, period, before)
        self.market.fetch.assert_not_awaited()

    async def test_no_older_stops(self):
        self.market.fetch.return_value = b'{"bars":[]}'
        data = await self.h.page({}, "EUR/USD", before=int(time.time()) - 100000)
        self.assertEqual(data["bars"], [])
        self.assertFalse(data["has_more"])

    async def test_network_error_returns_cache_with_warning(self):
        self.engine.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
        )
        self.h.record({})
        self.market.fetch.side_effect = ValueError("网络测试失败")
        data = await self.h.page({}, "EUR/USD")
        self.assertEqual(len(data["bars"]), 1)
        self.assertIn("网络", data["warning"])

    async def test_remote_candle_completes_partial_local_bar(self):
        values = bars(count=1)
        t = int(datetime.fromisoformat(values[0]["openTime"]).timestamp())
        self.engine.quotes["EUR/USD"] = dict(
            bid="1.12", ask="1.1202", timestamp=t + 1, tradeable=True
        )
        self.market.fetch.return_value = json.dumps({"bars": values}).encode()
        # Insert the thin locally captured candle explicitly, independently of quote freshness.
        self.engine.db.execute(
            "INSERT INTO candles VALUES(?,?,?,?,?,?)",
            (
                identity({}),
                "EUR/USD",
                "5m",
                t,
                json.dumps(
                    dict(time=t, open=1.1201, high=1.1201, low=1.1201, close=1.1201)
                ),
                t + 1,
            ),
        )
        result = await self.h.page({}, "EUR/USD")
        self.assertEqual(result["bars"][-1]["close"], 1.121)
        self.assertEqual(result["bars"][-1]["high"], 1.125)

    async def test_identical_requests_coalesced(self):
        import asyncio

        await asyncio.gather(self.h.page({}, "EUR/USD"), self.h.page({}, "EUR/USD"))
        self.assertEqual(self.market.fetch.await_count, 1)

    async def test_weekly_bootstrap_retains_older_cursor(self):
        self.market.fetch.return_value = json.dumps(
            {"bars": bars(count=1000, step=86400)}
        ).encode()
        result = await self.h.page({}, "EUR/USD", "1w")
        self.assertTrue(result["has_more"])
        self.assertLess(len(result["bars"]), 200)
        self.assertIsNotNone(result["next_before"])

    async def test_sina_day_string_safe_parse(self):
        raw = b'/*ignore*/kurumi("2026-10-01,1.1,1.0,1.3,1.2,|2026-10-02,1.2,1.1,1.4,1.3,");'
        result = parse_bars("sina", raw)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["low"], 1)
        self.assertEqual(result[1]["close"], 1.3)

    async def test_sina_day_endpoint_used(self):
        self.market.fetch.return_value = b'kurumi("2026-10-01,1.1,1.0,1.3,1.2,");'
        result = await self.h.page({"market_source": "sina"}, "EUR/USD", "1M")
        self.assertEqual(len(result["bars"]), 1)
        self.assertIn("getDayKLine", self.market.fetch.call_args.args[0])

    async def test_oanda_native_monthly(self):
        raw = dict(
            candles=[
                dict(
                    time="2026-10-01T00:00:00Z",
                    mid=dict(o="1.1", h="1.3", l="1.0", c="1.2"),
                )
            ]
        )
        self.market.fetch.return_value = json.dumps(raw).encode()
        result = await self.h.page(
            {"market_key": "secret", "market_account": "123-456"}, "EUR/USD", "1M"
        )
        self.assertEqual(len(result["bars"]), 1)
        self.assertEqual(self.market.fetch.call_args.args[1]["granularity"], "M")


class CalendarTests(unittest.TestCase):
    def test_months_are_calendar_not_thirty_days(self):
        feb = datetime(2024, 2, 29, 12, tzinfo=timezone.utc).timestamp()
        mar = datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(
            bucket(feb, "1M"),
            int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp()),
        )
        self.assertEqual(bucket(mar, "1M"), int(mar))

    def test_monday_week(self):
        wed = datetime(2026, 11, 4, 12, tzinfo=timezone.utc).timestamp()
        monday = datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp()
        self.assertEqual(bucket(wed, "1w"), int(monday))

    def test_aggregation_open_high_low_close(self):
        rows = [
            dict(
                time=int(datetime(2026, 10, day, tzinfo=timezone.utc).timestamp()),
                open=1.1,
                high=1.3 + day / 100,
                low=1.0 - day / 100,
                close=1.1 + day / 100,
            )
            for day in (1, 2, 3)
        ]
        merged = aggregate(rows, "1M", "biquote")[0]
        self.assertEqual(merged["open"], 1.1)
        self.assertAlmostEqual(merged["close"], 1.13)
        self.assertAlmostEqual(merged["high"], 1.33)
        self.assertAlmostEqual(merged["low"], 0.97)
