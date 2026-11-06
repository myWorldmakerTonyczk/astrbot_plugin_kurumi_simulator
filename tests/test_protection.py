"""Installed by the update script into the new plugin tests directory."""

import asyncio
import json
import time
import unittest
from types import SimpleNamespace

from src.core.engine import Engine
from src.tools._shared import console
from src.users.identity import Identity


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(":memory:")
        self.e.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
        )
        self.g = self.e.create(
            {"user_binding": {"type": "umo", "values": ["test:FriendMessage:1"]}}
        )
        self.id = self.g["id"]
        self.e.action(
            self.id,
            "open",
            dict(
                pair="EUR/USD",
                side="buy",
                units=1000,
                reason="测试",
                sl="1.09",
                tp="1.13",
            ),
        )
        self.p = self.e.get(self.id)["positions"][0]["id"]
        game = self.e.get(self.id)
        game["umo"] = "test:FriendMessage:1"
        self.e.save(game)
        self.plugin = SimpleNamespace(
            engine=self.e, identity=Identity(self.e), instance_locks={}
        )
        self.event = SimpleNamespace(
            unified_msg_origin="test:FriendMessage:1",
            get_sender_id=lambda: "1",
            platform_meta=SimpleNamespace(name="aiocqhttp"),
        )

    def tearDown(self):
        self.e.db.close()

    def test_profit_lock_above_entry(self):
        self.e.quotes["EUR/USD"].update(bid="1.12", ask="1.1202")
        self.e.action(
            self.id,
            "protect",
            dict(position=self.p, sl="1.11", reason="锁定利润"),
            "ai",
        )
        position = self.e.get(self.id)["positions"][0]
        self.assertEqual(position["sl"], "1.11")
        self.assertEqual(position["tp"], "1.13")
        self.assertEqual(self.e.logs(self.id)[0]["action"], "protect")

    def test_cancel_only_sl(self):
        self.e.action(
            self.id,
            "protect",
            dict(position=self.p, sl=0, tp=-1, reason="取消止损"),
            "ai",
        )
        position = self.e.get(self.id)["positions"][0]
        self.assertEqual(position["sl"], "")
        self.assertEqual(position["tp"], "1.13")

    def test_reject_crossed_line_atomic(self):
        with self.assertRaises(ValueError):
            self.e.action(
                self.id,
                "protect",
                dict(position=self.p, sl="1.095", tp="1.08", reason="无效"),
                "ai",
            )
        self.assertEqual(self.e.get(self.id)["positions"][0]["sl"], "1.09")

    def test_edited_stop_executes(self):
        self.e.action(
            self.id, "protect", dict(position=self.p, sl="1.099", reason="收紧"), "ai"
        )
        self.e.quotes["EUR/USD"].update(bid="1.098", ask="1.0982")
        self.e.tick(self.id)
        self.assertEqual(self.e.get(self.id)["positions"], [])

    def test_stale_quote_blocks_change(self):
        self.e.quotes["EUR/USD"]["timestamp"] -= 60
        with self.assertRaises(ValueError):
            self.e.action(
                self.id, "protect", dict(position=self.p, sl=0, reason="test"), "ai"
            )

    def test_journal_filters_and_paginates(self):
        self.e.action(self.id, "deposit", dict(amount=2000))
        def query(**options):
            reply = asyncio.run(console(self.plugin, self.event, "logs", json.dumps(options)))
            return json.loads(reply)["result"]

        result = query(pair="EUR/USD")["logs"]
        self.assertEqual([row["action"] for row in result], ["open"])
        self.e.action(self.id, "observe", dict(reason="test"))
        first = query(page_size=1, pages=2, filter="operations")
        self.assertEqual([row["action"] for row in first["logs"]], ["deposit", "open"])
        self.assertIsNone(first["next_page"])
        latest = query(page_size=1)
        self.assertEqual(latest["logs"][0]["action"], "observe")
        self.e.action(self.id, "observe", dict(reason="new event"))
        older = query(page=latest["next_page"], page_size=1, before=latest["before"])
        self.assertEqual(older["logs"][0]["action"], "deposit")
        self.assertEqual(query(sort="oldest")["logs"][0]["action"], "create")

    def test_other_session_has_no_access(self):
        other = SimpleNamespace(
            unified_msg_origin="test:FriendMessage:2",
            get_sender_id=lambda: "2",
            platform_meta=SimpleNamespace(name="aiocqhttp"),
        )
        self.assertIn("绑定", asyncio.run(console(self.plugin, other, "state", "{}")))
        self.assertFalse(json.loads(asyncio.run(console(self.plugin, other, "logs", "{}")))["ok"])

    def test_tool_rejects_funding(self):
        result = asyncio.run(
            console(
                self.plugin, self.event, "deposit", '{"amount":1000,"reason":"test"}'
            )
        )
        self.assertIn("无此操作权限", result)
