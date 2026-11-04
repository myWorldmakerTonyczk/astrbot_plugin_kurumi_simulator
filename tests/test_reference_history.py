import json
import unittest
from unittest.mock import AsyncMock
from src.core.engine import Engine
from src.market_data.market import Market
from src.market_data.history import History, identity


class ReferenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.e = Engine(":memory:")
        self.m = Market(self.e)
        self.h = History(self.e, self.m)
        self.settings = {"history_source": "frankfurter"}
        self.rows = [
            {"date": "2026-10-28", "base": "EUR", "quote": "USD", "rate": 1.1},
            {"date": "2026-10-29", "base": "EUR", "quote": "USD", "rate": 1.2},
        ]
        self.m.fetch = AsyncMock(return_value=json.dumps(self.rows).encode())

    def tearDown(self):
        self.e.db.close()

    async def test_reference_and_persistent_window_cache(self):
        data = await self.h.page(self.settings, "EUR/USD", "1d")
        self.assertEqual(len(data["bars"]), 2)
        self.assertTrue(data["reference"])
        self.assertEqual(self.e.quotes, {})
        again = History(self.e, self.m)
        await again.page(self.settings, "EUR/USD", "1d")
        self.assertEqual(self.m.fetch.await_count, 1)

    async def test_only_new_dates_after_hour(self):
        await self.h.page(self.settings, "EUR/USD", "1d")
        self.e.db.execute("UPDATE reference_ranges SET checked=0")
        await self.h.page(self.settings, "EUR/USD", "1d")
        self.assertEqual(self.m.fetch.call_args.args[1]["from"], "2026-10-29")

    async def test_weekly_last_reference_not_ohlc(self):
        data = await self.h.page(self.settings, "EUR/USD", "1w")
        self.assertEqual(len(data["bars"]), 1)
        bar = data["bars"][0]
        self.assertEqual(bar["close"], 1.2)
        self.assertEqual(bar["open"], bar["high"])
        self.assertEqual(bar["low"], bar["close"])

    async def test_minute_rejected(self):
        with self.assertRaises(ValueError):
            await self.h.page(self.settings, "EUR/USD", "5m")
        self.m.fetch.assert_not_awaited()

    async def test_failure_keeps_local(self):
        data = await self.h.page(self.settings, "EUR/USD", "1d")
        self.e.db.execute("UPDATE reference_ranges SET checked=0")
        self.m.fetch.side_effect = TimeoutError()
        again = await self.h.page(self.settings, "EUR/USD", "1d")
        self.assertEqual(data["bars"], again["bars"])
        self.assertTrue(again["warning"])

    def test_reference_identity_independent_of_live_feed(self):
        self.assertEqual(
            identity(dict(self.settings, market_source="sina")),
            identity(dict(self.settings, market_source="biquote")),
        )
        self.assertNotEqual(
            identity(self.settings), identity({"history_source": "market"})
        )
