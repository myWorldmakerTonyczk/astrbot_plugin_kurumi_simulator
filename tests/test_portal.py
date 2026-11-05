import unittest
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from src.agent.decisions import DecisionService
from src.core.engine import Engine
from src.diary.store import DiaryStore
from src.portal.server import COOKIE, Portal

ORIGIN = "https://panel.example.test"
POST = {"Origin": ORIGIN}


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = Engine(":memory:")
        self.addCleanup(self.engine.db.close)
        self.first = self.engine.create({"user_binding": {"type": "umo", "values": ["qq:FriendMessage:11111"]}})
        self.other = self.engine.create({"user_binding": {"type": "umo", "values": ["qq:FriendMessage:22222"]}})
        self.engine.action(self.first["id"], "plan", {"text": "本人的私人策略"})

        async def page(*args):
            return {"bars": []}

        plugin = SimpleNamespace(engine=self.engine, settings=lambda: {}, history=SimpleNamespace(page=page))
        DiaryStore(self.engine)
        DecisionService(plugin)
        self.portal = Portal(plugin)
        self.portal.config.update(enabled=True, origin=ORIGIN)
        self.client = TestClient(TestServer(self.portal.app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def exchange(self, mode):
        token = self.portal.access.issue(self.first["owner_id"], self.first["id"], mode)
        blocked = await self.client.post("/api/exchange", json={"token": token})
        self.assertEqual(blocked.status, 403)
        response = await self.client.post("/api/exchange", json={"token": token}, headers=POST)
        self.assertEqual(response.status, 200)
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        reused = await self.client.post("/api/exchange", json={"token": token}, headers=POST)
        self.assertEqual(reused.status, 400)
        return {"Cookie": f"{COOKIE}={cookie.value}"}

    async def test_read_link_replay_is_scoped_and_revocable(self):
        root = await self.client.get("/")
        self.assertEqual(root.status, 200)
        self.assertEqual(root.headers["Referrer-Policy"], "no-referrer")
        await root.read()
        denied = await self.client.get("/api/review")
        self.assertEqual(denied.status, 401)
        headers = await self.exchange("read")
        response = await self.client.get("/api/review", headers=headers)
        data = await response.json()
        self.assertEqual(response.status, 200, data)
        self.assertIn("本人的私人策略", str(data["events"]))
        response = await self.client.get("/api/review", params={"game": self.other["id"]}, headers=headers)
        self.assertEqual(response.status, 403)
        self.portal.access.revoke_links(self.first["id"])
        response = await self.client.get("/api/review", headers=headers)
        self.assertEqual(response.status, 401)

    async def test_summary_does_not_return_strategy_or_account_name(self):
        headers = await self.exchange("summary")
        response = await self.client.get("/api/review", headers=headers)
        data = await response.json()
        self.assertEqual(response.status, 200, data)
        self.assertFalse(data["private"])
        self.assertEqual(data["name"], "虚拟交易复盘")
        self.assertEqual(data["baseline"], "")
        self.assertEqual(data["diaries"], [])
        self.assertNotIn("本人的私人策略", str(data))
