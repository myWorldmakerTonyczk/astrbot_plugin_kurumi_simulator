import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace

from src.agent.decision_settings import settings
from src.core.availability import WEEKEND, inside_weekly_window, run_automatic
from src.core.engine import Engine


class AvailabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_weekend_bounds_and_daylight_saving(self):
        for stamp, expected in (
            ("2026-11-06T21:58:00+00:00", False),
            ("2026-11-06T21:59:00+00:00", True),
            ("2026-11-08T22:04:00+00:00", True),
            ("2026-11-08T22:05:00+00:00", False),
            ("2026-07-03T20:59:00+00:00", True),
        ):
            self.assertEqual(inside_weekly_window(datetime.fromisoformat(stamp).timestamp(), WEEKEND), expected)

    def test_custom_window_and_validation(self):
        config = settings(dict(weekend_zone="Asia/Shanghai", weekend_start_day=5,
                               weekend_start_time="08:00", weekend_end_day=0, weekend_end_time="09:00"))
        self.assertTrue(inside_weekly_window(datetime.fromisoformat("2026-11-08T12:00:00+08:00").timestamp(), config))
        with self.assertRaises(ValueError):
            settings(dict(weekend_start_time="99:99"))

    async def test_pause_cancels_running_automatic_work(self):
        engine = Engine(":memory:")
        self.addCleanup(engine.db.close)
        game = engine.create({})
        engine.quotes["EUR/USD"] = dict(bid="1.1000", ask="1.1002", tradeable=True, timestamp=__import__("time").time())
        engine.action(game["id"], "open", dict(pair="EUR/USD", side="buy", units="100", sl="1.0990", reason="test"))
        plugin = SimpleNamespace(engine=engine)
        ready = asyncio.Event()
        async def work():
            ready.set()
            await asyncio.Future()
        task = asyncio.create_task(run_automatic(plugin, game["id"], work()))
        await ready.wait()
        engine.action(game["id"], "pause", {}, "human")
        for running in plugin.automatic_tasks[game["id"]]:
            running.cancel()
        with self.assertRaisesRegex(ValueError, "已暂停"):
            await task
        self.assertFalse(plugin.automatic_tasks)
        engine.quotes["EUR/USD"] = dict(bid="1.0980", ask="1.0982", tradeable=True, timestamp=__import__("time").time())
        engine.tick(game["id"])
        self.assertEqual(engine.get(game["id"])["status"], "paused")
        self.assertEqual(engine.get(game["id"])["positions"], [])
