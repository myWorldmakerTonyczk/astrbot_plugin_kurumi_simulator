import json
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.market import (
    Market,
    parse_biquote,
    parse_sina,
    source,
    validate_url,
    signature,
)
from src.market_settings import merge_settings, public_settings


def item(age=0, **changes):
    result = dict(
        bid=1.12,
        ask=1.1201,
        timestamp=datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat(),
        marketState="open",
        stale=False,
    )
    result.update(changes)
    return result


class ParseTests(unittest.TestCase):
    def test_biquote_bid_ask_timestamp(self):
        q = parse_biquote({"EURUSD": item()})["EUR/USD"]
        self.assertEqual(q["bid"], "1.12")
        self.assertEqual(q["ask"], "1.1201")
        self.assertTrue(q["tradeable"])

    def test_stale_and_closed_never_tradeable(self):
        for value in (item(age=60), item(stale=True), item(marketState="closed")):
            self.assertFalse(parse_biquote({"EURUSD": value})["EUR/USD"]["tradeable"])

    def test_bad_price_and_future_skipped(self):
        for value in (
            item(bid=-1),
            item(ask=1),
            item(age=-3600),
            item(timestamp="bad"),
        ):
            self.assertEqual(parse_biquote({"EURUSD": value}), {})

    def test_sina_china_time(self):
        text = 'var hq_str_fx_seurusd="15:00:00,1.12,1.1201,1,2,3,4,5,6,欧元,0,0,0,,0,0,,2026-11-04";'
        now = datetime(2026, 11, 4, 7, 0, 1, tzinfo=timezone.utc).timestamp()
        q = parse_sina(text, now)["EUR/USD"]
        self.assertTrue(q["tradeable"])
        self.assertEqual(q["timestamp"], now - 1)
        self.assertFalse(parse_sina(text, now + 60)["EUR/USD"]["tradeable"])

    def test_sina_does_not_eval_js_or_empty(self):
        self.assertEqual(
            parse_sina('throw new Error("bad");var hq_str_fx_seurusd="";'), {}
        )

    def test_new_and_old_default(self):
        self.assertEqual(source({}), "biquote")
        self.assertEqual(source({"market_key": "preserved"}), "oanda")

    def test_secret_not_in_payload(self):
        s = merge_settings({"market_key": "secret"}, {"market_source": "sina"})
        self.assertEqual(s["market_key"], "secret")
        self.assertNotIn("secret", json.dumps(public_settings(s)))
        self.assertIn("https://hq.sinajs.cn/list=", json.dumps(public_settings(s)))

    def test_empty_key_preserves(self):
        s = merge_settings({"market_key": "secret"}, {"market_key": ""})
        self.assertEqual(s["market_key"], "secret")
        self.assertEqual(s["market_source"], "oanda")

    def test_url_validation(self):
        for url in (
            "http://example.com",
            "https://127.0.0.1",
            "https://[::1]",
            "https://localhost/foo",
            "https://user:pass@example.com",
            "https://example.com/#x",
        ):
            with self.assertRaises(ValueError):
                validate_url(url)
        validate_url("https://example.com/api/latest")

    def test_custom_urls_and_reset(self):
        settings = merge_settings(
            {}, dict(market_source="biquote", biquote_url="https://example.com/feed")
        )
        self.assertEqual(settings["biquote_url"], "https://example.com/feed")
        reset = merge_settings(settings, dict(biquote_url=""))
        self.assertEqual(reset["biquote_url"], "https://biquote.io/api/latest")
        self.assertNotEqual(signature(settings), signature(reset))

    def test_invalid_settings_rejected(self):
        for change in (
            {"market_source": "unknown"},
            {"market_key": False},
            {"unknown": "x"},
            {"sina_url": "http://example.com"},
        ):
            with self.assertRaises(ValueError):
                merge_settings({}, change)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_free_source_never_receives_saved_key(self):
        market = Market(SimpleNamespace(quotes={}))
        market.fetch = AsyncMock(return_value=json.dumps({"EURUSD": item()}).encode())
        await market.refresh({"market_source": "biquote", "market_key": "secret"})
        args = market.fetch.call_args
        self.assertNotIn("secret", str(args))
        self.assertEqual(args.args[0], "https://biquote.io/api/latest")
        self.assertEqual(len(args.args[1]), 6)

    async def test_custom_biquote_and_clear_missing_quotes(self):
        market = Market(SimpleNamespace(quotes={"USD/JPY": {"old": True}}))
        market.fetch = AsyncMock(return_value=json.dumps({"EURUSD": item()}).encode())
        await market.refresh(
            {"market_source": "biquote", "biquote_url": "https://example.com/feed"}
        )
        self.assertEqual(market.fetch.call_args.args[0], "https://example.com/feed")
        self.assertNotIn("USD/JPY", market.engine.quotes)

    async def test_sina_default_url(self):
        market = Market(SimpleNamespace(quotes={}))
        china = datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc)
        row = (
            [china.strftime("%H:%M:%S"), "1.12", "1.1201"]
            + ["0"] * 14
            + [china.strftime("%Y-%m-%d")]
        )
        market.fetch = AsyncMock(
            return_value=('var hq_str_fx_seurusd="' + ",".join(row) + '";').encode()
        )
        await market.refresh({"market_source": "sina", "market_key": "secret"})
        args = market.fetch.call_args
        self.assertTrue(args.args[0].startswith("https://hq.sinajs.cn/list=fx_seurusd"))
        self.assertNotIn("secret", str(args))

    async def test_no_quotes_does_not_destroy_old_cache(self):
        market = Market(SimpleNamespace(quotes={"old": True}))
        market.fetch = AsyncMock(return_value=b"{}")
        with self.assertRaises(ValueError):
            await market.refresh({"market_source": "biquote"})
        self.assertEqual(market.engine.quotes, {"old": True})

    async def test_legacy_oanda_kept_fixed(self):
        market = Market(SimpleNamespace(quotes={}))
        p = item()
        body = {
            "prices": [
                dict(
                    instrument="EUR_USD",
                    bids=[{"price": "1.12"}],
                    asks=[{"price": "1.1201"}],
                    time=p["timestamp"],
                    status="tradeable",
                )
            ]
        }
        market.fetch = AsyncMock(return_value=json.dumps(body).encode())
        await market.refresh({"market_key": "secret", "market_account": "123-456"})
        self.assertTrue(
            market.fetch.call_args.args[0].startswith(
                "https://api-fxpractice.oanda.com/"
            )
        )
        self.assertEqual(
            market.fetch.call_args.args[2]["Authorization"], "Bearer secret"
        )


class SinaRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_source_fallback_headers(self):
        market = Market(SimpleNamespace(quotes={}))
        china = datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc)
        row = (
            [china.strftime("%H:%M:%S"), "1.12", "1.1201"]
            + ["0"] * 14
            + [china.strftime("%Y-%m-%d")]
        )
        raw = ('var hq_str_fx_seurusd="' + ",".join(row) + '";').encode()
        market.fetch = AsyncMock(side_effect=[ValueError("HTTP403"), raw])
        await market.refresh({"market_source": "sina"})
        self.assertEqual(market.fetch.await_count, 2)
        retry = market.fetch.call_args
        self.assertEqual(retry.args[0], "https://hq.sinajs.cn/")
        self.assertIn("list", retry.args[1])
        self.assertIn("Referer", retry.args[2])

    async def test_custom_url_not_silently_replaced(self):
        market = Market(SimpleNamespace(quotes={}))
        market.fetch = AsyncMock(side_effect=ValueError("HTTP403"))
        with self.assertRaises(ValueError):
            await market.refresh(
                {"market_source": "sina", "sina_url": "https://example.com/list="}
            )
        self.assertEqual(market.fetch.await_count, 1)
