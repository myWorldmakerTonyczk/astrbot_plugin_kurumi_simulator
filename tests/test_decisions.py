import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.core.engine import Engine
from src.agent.decisions import DecisionService
from src.agent.decision_settings import settings


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine(":memory:")
        self.game = self.engine.create({})
        self.limits = settings()
        self.plugin = SimpleNamespace(
            engine=self.engine,
            settings=lambda: {"decision_limits": self.limits},
            context=SimpleNamespace(get_provider_by_id=lambda _: object()),
        )
        self.runner = AsyncMock(return_value={"summary": "已完成看盘"})
        self.service = DecisionService(self.plugin, self.runner)

    def tearDown(self):
        self.engine.db.close()

    def event(self, action="close", reason="触发止损", detail=None):
        return self.engine.log(
            self.engine.get(self.game["id"]), "system", action, reason, detail or {}
        )

    async def test_manual_coalesces_and_rate_survives_restart(self):
        game = self.engine.get(self.game["id"])
        game.update(provider="test", status="ended")
        self.engine.save(game)
        first = self.service.request_manual(game["id"], 1000)
        self.assertEqual(
            self.service.request_manual(game["id"], 1001)["job_id"], first["job_id"]
        )
        await self.service.process_one(1000)
        self.service.request_manual(game["id"], 1100)
        self.assertFalse(await self.service.process_one(1100))
        replacement = DecisionService(self.plugin, self.runner)
        self.assertEqual(replacement.next_allowed(game["id"], 1100), 1600)
        self.assertTrue(await replacement.process_one(1600))
        self.assertEqual(self.runner.await_count, 2)

    async def test_hourly_cap_and_cross_instance_independence(self):
        self.limits["hourly_limit"] = 1
        self.service.enqueue(self.game["id"], "手动看盘", now=1000)
        await self.service.process_one(1000)
        self.service.enqueue(self.game["id"], "手动看盘", now=1600)
        self.assertFalse(await self.service.process_one(1600))
        self.assertEqual(self.service.next_allowed(self.game["id"], 1600), 4600)
        other = self.engine.create({})
        self.service.enqueue(other["id"], "手动看盘", now=1600)
        self.assertTrue(await self.service.process_one(1600))

    async def test_risks_merged_and_cursor_not_replayed(self):
        self.event()
        self.event(reason="触发止盈")
        self.event(reason="模拟强平", detail={"kind": "liquidation"})
        self.event(action="margin_call", reason="保证金不足", detail={"level": "80"})
        self.event(action="end", reason="游戏结束", detail={"bankrupt": True})
        self.service.scan(1000)
        self.service.scan(1001)
        self.assertEqual(
            self.engine.db.execute("SELECT count(*) FROM decision_jobs").fetchone()[0],
            1,
        )
        self.assertEqual(self.service.state(self.game["id"], 1000)["queued_events"], 5)
        await self.service.process_one(1000)
        self.assertEqual(
            {e["kind"] for e in self.runner.call_args.kwargs["events"]},
            {"stop_loss", "take_profit", "liquidation", "margin_call", "end"},
        )
        replacement = DecisionService(self.plugin, self.runner)
        replacement.scan(2000)
        self.assertIsNone(replacement.active(self.game["id"]))

    async def test_new_event_during_running_is_not_lost(self):
        self.event()
        self.service.scan(1000)

        async def run(*args, **kwargs):
            self.event(reason="触发止盈")
            self.service.scan(1010)
            return {"summary": "first"}

        self.service.runner = run
        await self.service.process_one(1000)
        self.assertEqual(self.service.state(self.game["id"], 1010)["state"], "pending")
        self.assertEqual(self.service.state(self.game["id"], 1010)["queued_events"], 1)

    async def test_disabled_event_and_historical_upgrade_not_replayed(self):
        self.limits["stop_loss"] = False
        self.event()
        self.service.scan(1000)
        self.assertIsNone(self.service.active(self.game["id"]))
        self.engine.db.execute("DELETE FROM decision_cursor")
        replacement = DecisionService(self.plugin, self.runner)
        replacement.scan(1000)
        self.assertIsNone(replacement.active(self.game["id"]))

    async def test_serial_worker_failure_is_visible_and_limited(self):
        self.service.enqueue(self.game["id"], "手动看盘", now=1000)
        self.runner.side_effect = RuntimeError("private upstream error")
        await asyncio.gather(
            self.service.process_one(1000), self.service.process_one(1000)
        )
        self.assertEqual(self.runner.await_count, 1)
        state = self.service.state(self.game["id"], 1000)
        self.assertEqual(state["state"], "failed")
        self.assertNotIn("private", state["error"])
        self.assertEqual(state["next_allowed"], 1600)

    def test_recovery_merges_and_deletion_cleans_jobs(self):
        job = self.service.enqueue(self.game["id"], "手动看盘", now=1000)
        self.engine.db.execute(
            "UPDATE decision_jobs SET state='running' WHERE id=?", (job,)
        )
        self.service.enqueue(
            self.game["id"], "风险事件复盘", [{"id": 22, "kind": "end"}], 1010
        )
        self.service.recover()
        self.assertEqual(
            self.engine.db.execute(
                "SELECT count(*) FROM decision_jobs WHERE state='pending'"
            ).fetchone()[0],
            1,
        )
        self.engine.delete(self.game["id"])
        self.assertFalse(
            self.engine.db.execute("SELECT 1 FROM decision_jobs").fetchone()
        )

    def test_limits_and_pause_survives_reload(self):
        for changes in ({"cooldown": 599}, {"hourly_limit": 7}, {"stop_loss": "yes"}):
            with self.assertRaises(ValueError):
                settings(changes)
        game = self.engine.get(self.game["id"])
        game.update(status="paused", auto=True)
        self.engine.save(game)
        DecisionService(self.plugin)
        migrated = self.engine.get(game["id"])
        self.assertEqual(migrated["status"], "paused")
        self.assertTrue(migrated["auto"])

    async def test_disabling_periodic_cancels_waiting_timer_only(self):
        self.service.enqueue(self.game["id"], "定时看盘", now=1000)
        self.assertFalse(await self.service.process_one(1000))
        self.runner.assert_not_awaited()
        self.service.enqueue(
            self.game["id"], "风险事件复盘", [{"id": 99, "kind": "end"}], now=1001
        )
        self.assertTrue(await self.service.process_one(1001))
