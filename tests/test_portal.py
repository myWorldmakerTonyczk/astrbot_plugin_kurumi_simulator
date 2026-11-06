import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from src.agent.decisions import DecisionService
from src.core.engine import Engine
from src.diary.store import DiaryStore
from src.portal.server import COOKIE, Portal
from src.users.identity import Identity
from src.portal.chat import chat_owner
from src.tools.send_panel import build
from src.tools.send_review_image import build as build_image_tool

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

        plugin = SimpleNamespace(
            engine=self.engine, settings=lambda: {}, history=SimpleNamespace(page=page),
            instance_locks={}, identity=Identity(self.engine),
        )
        plugin.diary = SimpleNamespace(store=DiaryStore(self.engine))
        DecisionService(plugin)
        self.portal = Portal(plugin)
        plugin.portal = self.portal
        self.portal.config.update(enabled=True, origin=ORIGIN)
        self.client = TestClient(TestServer(self.portal.app(), access_log=None), headers={"Host": "panel.example.test"})
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

    async def test_portal_records_require_owner_or_private_read_link(self):
        gid = self.first["id"]
        for path in ("/api/journal", "/api/notebook"):
            response = await self.client.get(path, params={"game": gid})
            self.assertEqual(response.status, 401)
        summary = await self.exchange("summary")
        for path in ("/api/journal", "/api/notebook"):
            response = await self.client.get(path, params={"game": gid}, headers=summary)
            self.assertEqual(response.status, 403)
        read = await self.exchange("read")
        for path in ("/api/journal", "/api/notebook"):
            response = await self.client.get(path, params={"game": gid}, headers=read)
            self.assertEqual(response.status, 200)
            response = await self.client.get(path, params={"game": self.other["id"]}, headers=read)
            self.assertEqual(response.status, 403)

    async def test_shared_view_files_and_workspace_data(self):
        response = await self.client.get("/workspace/", allow_redirects=False)
        self.assertEqual(response.status, 302)
        read = await self.exchange("read")
        response = await self.client.get("/workspace/", headers=read)
        self.assertIn("data-remote-workspace", await response.text())
        for path, mime in (
            ("assets/avatar.png", "image/png"),
            ("assets/hero-green.png", "image/png"),
            ("app.js", "text/javascript"),
            ("style.css", "text/css"),
        ):
            response = await self.client.get("/workspace/" + path)
            self.assertEqual((response.status, response.content_type), (200, mime))
        self.assertEqual((await self.client.get("/workspace/assets/private.png")).status, 404)
        for route in ("workspace", "history", "diaries"):
            response = await self.client.get("/api/" + route, headers=read, params={"game": self.first["id"]})
            self.assertEqual(response.status, 200)
            response = await self.client.get("/api/" + route, headers=read, params={"game": self.other["id"]})
            self.assertEqual(response.status, 403)
        response = await self.client.get("/api/workspace", headers=read, params={"game": self.first["id"]})
        game = (await response.json())["current"]["game"]
        self.assertEqual(game["plan"], "本人的私人策略")
        self.assertFalse(game["trade"])
        self.assertNotIn("reference_umo", game)

    async def test_account_login_and_trade_require_owner_and_explicit_grant(self):
        owner = self.first["owner_id"]
        gid = self.first["id"]
        user, password = await self.portal.accounts.issue(owner)
        self.assertTrue(password)
        self.assertEqual(user, "qq:FriendMessage:11111")
        self.assertEqual(await self.portal.accounts.issue(owner), (user, ""))
        wrong = await self.client.post("/api/login", json={"username": user, "password": "wrong"}, headers=POST)
        self.assertEqual(wrong.status, 401)
        logged_in = await self.client.post("/api/login", json={"username": user, "password": password}, headers=POST)
        self.assertEqual(logged_in.status, 200)
        headers = POST | {"Cookie": f"{COOKIE}={logged_in.cookies[COOKIE].value}"}
        response = await self.client.get("/api/session", headers=headers)
        self.assertEqual([g["id"] for g in (await response.json())["games"]], [gid])
        foreign = await self.client.get("/api/account", params={"game": self.other["id"]}, headers=headers)
        self.assertEqual(foreign.status, 403)
        payload = {
            "action": "open", "request_id": "0123456789abcdef",
            "params": {"pair": "EUR/USD", "side": "buy", "units": "1000", "reason": "网页测试"},
        }
        refused = await self.client.post("/api/action", params={"game": gid}, json=payload, headers=headers)
        self.assertEqual(refused.status, 403)
        self.portal.accounts.allow_trade(gid, True)
        read_only = await self.exchange("read")
        refused = await self.client.post("/api/action", params={"game": gid}, json=payload, headers=POST | read_only)
        self.assertEqual(refused.status, 403)
        self.engine.quotes["EUR/USD"] = dict(bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True)
        for _ in range(2):
            filled = await self.client.post("/api/action", params={"game": gid}, json=payload, headers=headers)
            self.assertEqual(filled.status, 200, await filled.text())
        self.assertEqual(len(self.engine.get(gid)["positions"]), 1)
        blocked = await self.client.post(
            "/api/action", params={"game": gid}, json=dict(payload, action="deposit"), headers=headers,
        )
        self.assertEqual(blocked.status, 403)
        self.portal.accounts.allow_trade(gid, False)
        refused = await self.client.post("/api/action", params={"game": gid}, json=payload, headers=headers)
        self.assertEqual(refused.status, 403)
        self.portal.accounts.reset(owner)
        revoked = await self.client.get("/api/account", params={"game": gid}, headers=headers)
        self.assertEqual(revoked.status, 401)

    async def test_admin_password_replacement_revokes_existing_portal_login(self):
        owner = self.first["owner_id"]
        username, old_password = await self.portal.accounts.issue(owner)
        old_session = await self.portal.accounts.login(username, old_password)
        self.assertTrue(old_session)
        await self.portal.accounts.set_password(owner, "new-test-password")
        old = await self.client.get("/api/account", params={"game": self.first["id"]}, headers={"Cookie": f"{COOKIE}={old_session}"})
        self.assertEqual(old.status, 401)
        self.assertIsNone(await self.portal.accounts.login(username, old_password))
        self.assertTrue(await self.portal.accounts.login(username, "new-test-password"))

    async def test_existing_random_user_gets_credentials_only_at_configured_umo(self):
        game = self.engine.create({"user_binding": {"type": "random", "values": []}})
        gid = game["id"]
        owner = game["owner_id"]
        event = SimpleNamespace(
            unified_msg_origin="qq:FriendMessage:33333",
            get_sender_id=lambda: "33333",
            platform_meta=SimpleNamespace(name="qq"),
            send=AsyncMock(),
        )
        with self.assertRaises(ValueError):
            chat_owner(self.portal.plugin, event)
        with self.assertRaisesRegex(ValueError, "其他用户"):
            self.portal.accounts.bind_chat(gid, ["qq:FriendMessage:11111"])
        self.portal.accounts.bind_chat(gid, [event.unified_msg_origin])
        self.assertEqual(chat_owner(self.portal.plugin, event), owner)
        # The HTTP listener is already running under TestServer.
        self.portal.runner = self.client.server
        handler = build(self.portal.plugin).handler
        result = await handler(event, "login")
        message = event.send.await_args.args[0].chain[0].text
        self.assertIn("首次密码", message)
        self.assertNotIn(self.portal.accounts.username(owner), result)
        self.assertNotIn("首次密码", result)
        await handler(event, "login")
        self.assertNotIn("首次密码：", event.send.await_args.args[0].chain[0].text)
        image_result = await build_image_tool(self.portal.plugin).handler(event, "drawdown")
        self.assertIn('"ok": true', image_result)
        image = event.send.await_args.args[0].chain[0]
        self.assertTrue(image.file.startswith("base64://"))
        event.unified_msg_origin = "qq:GroupMessage:33333"
        event.send.reset_mock()
        await handler(event, "login")
        event.send.assert_not_awaited()
        self.portal.accounts.bind_chat(gid, [])
        self.assertEqual(self.portal.accounts.username(owner), "")
