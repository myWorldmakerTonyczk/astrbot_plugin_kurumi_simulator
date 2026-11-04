import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.engine import Engine, dump
from src.identity import Identity
from src.tools import console, list_instances, select_instance
from src.trading import lock_for


def event(umo="bot:FriendMessage:123456", sender="123456", platform="aiocqhttp"):
    return SimpleNamespace(
        unified_msg_origin=umo,
        get_sender_id=lambda: sender,
        platform_meta=SimpleNamespace(name=platform),
    )


class ChatTradingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.e = Engine(":memory:")
        self.identity = Identity(self.e)
        self.a = self.e.create(
            {"user_binding": {"type": "random", "values": []}, "allow_deposit": False}
        )
        self.token = self.e.users()[0]["public_id"]
        self.b = self.e.create({"user_binding": {"type": "random", "values": []}})
        self.p = SimpleNamespace(
            engine=self.e,
            identity=self.identity,
            instance_locks={},
            settings=lambda: {},
            history=SimpleNamespace(page=AsyncMock(return_value={"bars": []})),
        )
        self.event = event()
        self.e.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
        )

    async def asyncTearDown(self):
        self.e.db.close()

    async def test_bearer_required_on_every_call_and_never_returned(self):
        data = json.loads(await list_instances(self.p, self.event, self.token))
        self.assertEqual([g["id"] for g in data["instances"]], [self.a["id"]])
        self.assertFalse(
            json.loads(await console(self.p, self.event, "state", "{}"))["ok"]
        )
        state = await console(self.p, self.event, "state", "{}", self.token)
        self.assertNotIn(self.token, state)
        self.assertNotIn("user_binding", state)

    async def test_rotated_id_immediately_rejected(self):
        await console(self.p, self.event, "state", "{}", self.token)
        new = self.e.rotate_user_id(self.a["owner_id"])["public_id"]
        self.assertFalse(
            json.loads(await console(self.p, self.event, "state", "{}", self.token))[
                "ok"
            ]
        )
        self.assertTrue(
            json.loads(await console(self.p, self.event, "state", "{}", new))["ok"]
        )

    async def test_cross_user_selection_and_position_denied(self):
        result = json.loads(
            await select_instance(self.p, self.event, self.b["id"], self.token)
        )
        self.assertFalse(result["ok"])
        self.e.action(self.b["id"], "open", dict(pair="EUR/USD", side="buy", units=100))
        pid = self.e.get(self.b["id"])["positions"][0]["id"]
        result = json.loads(
            await console(
                self.p,
                self.event,
                "close",
                dump(dict(position=pid, reason="close")),
                self.token,
            )
        )
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.e.get(self.b["id"])["positions"]), 1)

    async def test_multi_instance_selection_and_reference_grant(self):
        c = self.e.create({"user_binding": {"type": "random", "values": [self.token]}})
        result = json.loads(
            await console(self.p, self.event, "state", "{}", self.token)
        )
        self.assertFalse(result["ok"])
        await select_instance(self.p, self.event, c["id"], self.token)
        self.assertTrue(
            self.identity.can_reference(c["owner_id"], self.event.unified_msg_origin)
        )
        result = json.loads(
            await console(
                self.p,
                self.event,
                "plan",
                dump(dict(text="等待价格回落", reason="更新策略")),
                self.token,
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.e.get(c["id"])["plan"], "等待价格回落")
        self.assertEqual(self.e.get(self.a["id"])["plan"], "")

    async def test_qq_and_exact_umo_auto_binding(self):
        qq = self.e.create({"user_binding": {"type": "qq", "values": ["123456"]}})
        self.assertEqual(self.identity.selected(self.event)["id"], qq["id"])
        with self.assertRaises(ValueError):
            self.identity.principal(event(platform="discord"))
        umo = self.e.create(
            {"user_binding": {"type": "umo", "values": ["bot:FriendMessage:123456"]}}
        )
        self.assertEqual(self.identity.selected(self.event)["id"], umo["id"])

    async def test_group_rejected_even_with_token(self):
        result = json.loads(
            await list_instances(self.p, event("bot:GroupMessage:999"), self.token)
        )
        self.assertFalse(result["ok"])

    async def test_plan_reason_required_notes_and_recharge_unavailable(self):
        for action, body in [
            ("plan", {"text": "bad"}),
            ("notes", {"text": "note", "reason": "x"}),
            ("deposit", {"amount": 100, "reason": "x"}),
        ]:
            self.assertFalse(
                json.loads(
                    await console(self.p, self.event, action, dump(body), self.token)
                )["ok"]
            )
        with self.assertRaises(ValueError):
            self.e.action(self.a["id"], "deposit", {"amount": 1})

    async def test_busy_instance_rejects_writes_but_allows_read(self):
        async with lock_for(self.p, self.a["id"]):
            result = json.loads(
                await console(
                    self.p,
                    self.event,
                    "plan",
                    dump(dict(text="x", reason="x")),
                    self.token,
                )
            )
            self.assertFalse(result["ok"])
            self.assertTrue(
                json.loads(
                    await console(self.p, self.event, "state", "{}", self.token)
                )["ok"]
            )

    async def test_real_history_is_a_read_only_query(self):
        result = json.loads(
            await console(
                self.p,
                self.event,
                "history",
                dump(dict(pair="EUR/USD", period="1h", limit=30)),
                self.token,
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            self.p.history.page.call_args.args[0]["history_source"], "market"
        )
