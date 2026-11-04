import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from src.core.engine import Engine
from src.users.identity import Identity
from src.diary.settings import settings, bounds, due_before
from src.diary.scheduler import DiaryService


def stamp(text):
    return (
        datetime.fromisoformat(text)
        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        .timestamp()
    )


class DiaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine(":memory:")
        self.identity = Identity(self.engine)
        self.config = settings()
        self.plugin = SimpleNamespace(
            engine=self.engine,
            identity=self.identity,
            settings=lambda: {"diary": self.config},
        )
        self.writer = AsyncMock(return_value="今天认真想了想，明天继续观察。")
        self.diary = self.plugin.diary = DiaryService(self.plugin, writer=self.writer)
        self.game = self.create("bot:FriendMessage:123456")
        self.now = stamp("2026-11-05T00:10:00")

    def tearDown(self):
        self.engine.db.close()

    def create(self, umo):
        game = self.engine.create({"user_binding": {"type": "umo", "values": [umo]}})
        game["created"] = stamp("2026-11-04T01:00:00")
        self.engine.save(game)
        self.engine.db.execute("DELETE FROM logs WHERE game=?", (game["id"],))
        return game

    def logs(self, count, game=None, action="observe"):
        game = game or self.game
        for i in range(count):
            entry = self.engine.log(game, "ai", action, "观察理由", {})
            self.engine.db.execute(
                "UPDATE logs SET created=?,data=json_set(data,'$.created',?) WHERE seq=?",
                (
                    stamp("2026-11-04T12:00:00") + i,
                    stamp("2026-11-04T12:00:00") + i,
                    entry["id"],
                ),
            )

    def chat(self, game=None, when=None, token="你好"):
        game = game or self.game
        event = SimpleNamespace(
            unified_msg_origin=game["reference_umo"],
            get_sender_id=lambda: "123456",
            platform_meta=SimpleNamespace(name="aiocqhttp"),
            message_obj=SimpleNamespace(message_id="m1"),
        )
        self.diary.store.capture(
            self.plugin, event, "user", token, when or stamp("2026-11-04T13:00:00")
        )
        return event

    async def test_strict_threshold_and_idempotent_rescan(self):
        self.logs(2)
        self.diary.scan(self.now)
        self.assertEqual(self.diary.store.list(self.game["id"]), [])
        self.logs(1)
        self.diary.scan_key = None
        self.diary.scan(self.now)
        self.assertEqual(len(self.diary.store.list(self.game["id"])), 1)
        await self.diary.process_one(self.now)
        self.diary.scan_key = None
        self.diary.scan(self.now + 86400)
        await self.diary.process_one(self.now + 86400)
        self.writer.assert_awaited_once()
        self.assertEqual(self.diary.store.list(self.game["id"])[0]["status"], "success")

    async def test_chat_only_does_not_bypass_low_trade_threshold(self):
        self.chat()
        self.diary.scan(self.now)
        self.assertFalse(self.diary.store.list(self.game["id"]))
        self.config["chat_only"] = True
        self.diary.scan(self.now)
        self.assertEqual(len(self.diary.store.list(self.game["id"])), 1)
        self.logs(1)
        await self.diary.process_one(self.now)
        self.writer.assert_not_awaited()
        self.assertEqual(self.diary.store.list(self.game["id"])[0]["status"], "skipped")

    async def test_zero_chat_and_analysis_are_not_activity(self):
        self.config["chat_only"] = True
        self.logs(20, action="analysis")
        self.diary.scan(self.now)
        self.assertFalse(self.diary.store.list(self.game["id"]))

    async def test_due_time_and_backfill_older_than_yesterday(self):
        self.logs(3)
        self.diary.scan(self.now - 1)
        self.assertFalse(self.diary.store.list(self.game["id"]))
        self.diary.scan(self.now + 86400 * 4)
        self.assertEqual(self.diary.store.list(self.game["id"])[0]["day"], "2026-11-04")

    async def test_serial_global_queue_and_per_instance_isolation(self):
        other = self.create("bot:FriendMessage:234567")
        self.logs(3)
        self.logs(3, other)
        self.diary.scan(self.now)
        active, maximum = 0, 0

        async def generate(*args):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return "一篇日记"

        self.diary.writer = generate
        await asyncio.gather(
            self.diary.process_one(self.now), self.diary.process_one(self.now)
        )
        await self.diary.process_one(self.now)
        self.assertEqual(maximum, 1)
        for game in (self.game, other):
            self.assertEqual(self.diary.store.list(game["id"])[0]["status"], "success")

    async def test_failure_retry_and_restart_recovery(self):
        self.logs(3)
        self.diary.scan(self.now)
        self.writer.side_effect = RuntimeError("secret upstream response")
        await self.diary.process_one(self.now)
        row = self.diary.store.get(self.game["id"], "2026-11-04")
        self.assertEqual(row["status"], "failed")
        self.assertNotIn("secret", row["error"])
        self.assertFalse(await self.diary.process_one(self.now + 299))
        self.writer.side_effect = None
        self.assertTrue(await self.diary.process_one(self.now + 301))
        self.engine.db.execute("UPDATE diaries SET status='running'")
        replacement = DiaryService(self.plugin, self.writer)
        replacement.store.recover()
        self.assertEqual(
            replacement.store.list(self.game["id"])[0]["status"], "pending"
        )

    async def test_cancellation_returns_task_to_queue(self):
        self.logs(3)
        self.diary.scan(self.now)
        self.writer.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.diary.process_one(self.now)
        self.assertEqual(self.diary.store.list(self.game["id"])[0]["status"], "pending")

    async def test_archive_dedupe_redaction_scope_and_past_cutoff(self):
        event = self.chat(token="你好 krm_11111111111111111111")
        self.diary.store.capture(self.plugin, event, "user", "重复消息", self.now)
        self.assertEqual(
            self.engine.db.execute("SELECT count(*) FROM diary_chat").fetchone()[0], 1
        )
        event.message_obj.message_id = "future"
        self.diary.store.capture(self.plugin, event, "assistant", "未来的话", self.now)
        self.logs(3)
        future = self.engine.log(self.game, "ai", "observe", "未来操作", {})
        self.engine.db.execute(
            "UPDATE logs SET created=? WHERE seq=?", (self.now, future["id"])
        )
        self.diary.scan(self.now)
        job = self.diary.store.get(self.game["id"], "2026-11-04")
        chat = self.diary.store.records(self.plugin, job, "chat")
        self.assertEqual(len(chat["records"]), 1)
        self.assertNotIn("krm_", str(chat))
        self.assertNotIn(
            "未来操作", str(self.diary.store.records(self.plugin, job, "logs"))
        )
        self.game["reference_umo"] = "someone:FriendMessage:999999"
        self.engine.save(self.game)
        self.assertEqual(
            self.diary.store.records(self.plugin, job, "chat")["records"], []
        )

    async def test_deleting_instance_purges_queue_and_chat(self):
        self.logs(3)
        self.chat()
        self.diary.scan(self.now)
        self.engine.delete(self.game["id"])
        self.assertEqual(
            self.engine.db.execute("SELECT count(*) FROM diaries").fetchone()[0], 0
        )
        self.assertEqual(
            self.engine.db.execute("SELECT count(*) FROM diary_chat").fetchone()[0], 0
        )

    def test_config_validation_and_dst_day(self):
        for changes in (
            {"min_logs": 2.5},
            {"min_logs": True},
            {"time": "24:00"},
            {"timezone": "invalid"},
            {"chat_only": "yes"},
            {"extra": True},
        ):
            with self.assertRaises(ValueError):
                settings(changes)
        begin, end = bounds("2026-03-08", "America/New_York")
        self.assertEqual(end - begin, 23 * 3600)
        self.assertEqual(str(due_before(self.now, self.config)), "2026-11-04")

    def test_queue_persists_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            engine = Engine(path)
            game = engine.create({})
            service = DiaryService(SimpleNamespace(engine=engine))
            service.store.enqueue(game["id"], "2026-11-04", "Asia/Shanghai", 0, 1, 1)
            engine.db.close()
            engine = Engine(path)
            service = DiaryService(SimpleNamespace(engine=engine))
            self.assertEqual(service.store.list(game["id"])[0]["status"], "pending")
            engine.db.close()

    async def test_saving_instance_preserves_chat_and_diary(self):
        self.logs(3)
        self.chat()
        self.diary.scan(self.now)
        await self.diary.process_one(self.now)
        game = self.engine.get(self.game["id"])
        game["plan"] = "更新计划不会清空日记"
        self.engine.save(game)
        self.assertEqual(self.diary.store.list(game["id"])[0]["status"], "success")
        self.assertTrue(self.diary.store.has_chat(game["id"], 0, self.now))
