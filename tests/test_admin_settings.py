import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from src.core.engine import Engine
from src.users.identity import Identity
from src.users import policy
from src.agent.llm import settings as llm_settings, public as llm_public, tool_loop
from src.notifications.settings import validate, config, delivery_time, quiet
from src.notifications.service import NotificationService


def stamp(hhmm):
    return (
        datetime.fromisoformat("2026-11-06T" + hhmm)
        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        .timestamp()
    )


class AdminSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine(":memory:")
        self.identity = Identity(self.engine)
        self.game = self.engine.create(
            {"user_binding": {"type": "umo", "values": ["bot:FriendMessage:123456"]}}
        )
        self.plugin = SimpleNamespace(
            engine=self.engine,
            identity=self.identity,
            context=SimpleNamespace(
                tool_loop_agent=AsyncMock(return_value="platform-result"),
                get_provider_by_id=lambda _: object(),
            ),
            settings=lambda: {},
            diary=SimpleNamespace(config=lambda: {"enabled": False}),
        )
        self.service = NotificationService(self.plugin)
        self.service.send = AsyncMock()

    def tearDown(self):
        self.engine.db.close()

    def analysis(self):
        game = self.engine.get(self.game["id"])
        game["notifications"] = {**config(game), "analysis": True}
        self.engine.save(game)
        self.engine.log(
            self.engine.get(self.game["id"]),
            "ai",
            "analysis",
            "定时看盘",
            {"summary": "继续观察，不急着交易"},
        )

    def test_default_permissions_interval_and_notice_flags(self):
        access = policy.effective(self.engine, self.game)
        self.assertFalse(access["allow_custom_interval"])
        self.assertEqual(access["effective_interval"], 3600)
        self.assertTrue(access["allow_tool_notice"])
        self.assertTrue(access["allow_panel_notice"])
        for key in (
            "enabled",
            "liquidation",
            "margin_call",
            "deposit",
            "end",
        ):
            self.assertTrue(access["notifications"][key])
        self.assertFalse(access["notifications"]["use_window"])
        self.assertFalse(access["notifications"]["analysis"])
        self.assertFalse(access["notifications"]["random_delay"])

    def test_rename_updates_all_instances_and_preserves_id(self):
        other = self.engine.create({"user_binding": self.game["user_binding"]})
        before = self.engine.users()[0]
        values = {**policy.DEFAULTS, "interval": 7200}
        policy.update(
            self.engine, self.game["owner_id"], "新的名字", values, config(self.game)
        )
        after = self.engine.users()[0]
        self.assertEqual(before["public_id"], after["public_id"])
        self.assertEqual(len(after["instances"]), 2)
        self.assertEqual(after["bindings"][0]["value"], "bot:FriendMessage:123456")
        for game in (self.game, other):
            saved = self.engine.get(game["id"])
            self.assertEqual(saved["owner_name"], "新的名字")
            self.assertEqual(
                policy.effective(self.engine, saved)["effective_interval"], 7200
            )
        with self.assertRaises(ValueError):
            policy.update(
                self.engine, self.game["owner_id"], "", values, config(self.game)
            )

    def test_panel_and_tool_notification_permissions_enforced(self):
        uid = self.game["owner_id"]
        values = {
            **policy.DEFAULTS,
            "allow_panel_notice": False,
            "allow_tool_notice": False,
        }
        policy.update(self.engine, uid, "用户", values, config(self.game))
        for source in ("human", "ai"):
            with self.assertRaises(ValueError):
                policy.change_notices(
                    self.plugin, self.game["id"], {"enabled": False}, source
                )
        values["allow_tool_notice"] = True
        policy.update(self.engine, uid, "用户", values, config(self.game))
        policy.change_notices(self.plugin, self.game["id"], {"enabled": False}, "ai")
        self.assertFalse(config(self.engine.get(self.game["id"]))["enabled"])
        policy.update(self.engine, uid, "只改名字", values, config(self.game))
        self.assertFalse(config(self.engine.get(self.game["id"]))["enabled"])

    async def test_all_emergencies_wait_until_quiet_ends(self):
        self.analysis()
        for action, detail in (
            ("margin_call", {"level": "85"}),
            ("close", {"kind": "liquidation", "position": {"pair": "EUR/USD"}}),
            ("deposit", {"amount": "100"}),
            ("end", {"bankrupt": True}),
        ):
            self.engine.log(self.game, "system", action, "风险事件", detail)
        self.service.scan(stamp("02:00:00"))
        self.assertEqual(
            self.engine.db.execute("SELECT count(*) FROM notice_outbox").fetchone()[0],
            5,
        )
        # Force an erroneously old due time: delivery must still apply the current blacklist.
        self.engine.db.execute("UPDATE notice_outbox SET due=0")
        await self.service.flush(stamp("02:00:00"))
        self.service.send.assert_not_awaited()
        await self.service.flush(stamp("07:00:00"))
        self.assertEqual(self.service.send.await_count, 5)
        self.assertTrue(
            all(
                call.args[0] == self.game["reference_umo"]
                for call in self.service.send.await_args_list
            )
        )

    async def test_blacklist_rechecked_after_preferences_change(self):
        self.analysis()
        self.service.scan(stamp("10:00:00"))
        game = self.engine.get(self.game["id"])
        game["notifications"] = validate(
            {"analysis": True, "quiet_start": "09:00", "quiet_end": "11:00"}
        )
        self.engine.save(game)
        await self.service.flush(stamp("10:01:00"))
        self.service.send.assert_not_awaited()
        await self.service.flush(stamp("11:00:00"))
        self.service.send.assert_awaited_once()

    async def test_pending_reports_coalesce_without_postponing_slot(self):
        game = self.engine.get(self.game["id"])
        game["notifications"] = validate({"use_window": True, "random_delay": True})
        self.engine.save(game)
        self.analysis()
        with patch("src.notifications.settings.random.random", return_value=0.5):
            self.service.scan(stamp("08:00:00"))
        due = self.engine.db.execute("SELECT due FROM notice_outbox").fetchone()[0]
        self.analysis()
        self.service.scan(stamp("08:30:00"))
        rows = self.engine.db.execute("SELECT * FROM notice_outbox").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["due"], due)
        self.assertGreaterEqual(due, stamp("09:00:00"))
        self.assertLess(due, stamp("22:00:00"))

    async def test_failure_retries_without_replaying_success_after_restart(self):
        self.analysis()
        self.service.scan(stamp("10:00:00"))
        self.service.send.side_effect = RuntimeError("private upstream response")
        await self.service.flush(stamp("10:00:00"))
        row = self.engine.db.execute("SELECT * FROM notice_outbox").fetchone()
        self.assertEqual(row["state"], "failed")
        self.assertNotIn("private", row["error"])
        self.service.send.side_effect = None
        await self.service.flush(stamp("10:02:00"))
        self.assertEqual(self.service.send.await_count, 2)
        replacement = NotificationService(self.plugin)
        replacement.send = AsyncMock()
        replacement.scan(stamp("10:03:00"))
        await replacement.flush(stamp("10:03:00"))
        replacement.send.assert_not_awaited()

    async def test_unverified_session_and_disabled_notices_do_not_send(self):
        self.analysis()
        self.service.scan(stamp("10:00:00"))
        game = self.engine.get(self.game["id"])
        game["reference_umo"] = "other:FriendMessage:654321"
        self.engine.save(game)
        await self.service.flush(stamp("10:00:00"))
        self.service.send.assert_not_awaited()
        game["notifications"] = validate({"enabled": False})
        self.engine.save(game)
        await self.service.flush(stamp("10:10:00"))
        self.assertEqual(
            self.engine.db.execute("SELECT state FROM notice_outbox").fetchone()[0],
            "cancelled",
        )

    def test_time_boundaries_overnight_and_no_available_slot(self):
        values = validate()
        self.assertTrue(quiet(stamp("00:00:00"), values))
        self.assertTrue(quiet(stamp("06:59:59"), values))
        self.assertFalse(quiet(stamp("07:00:00"), values))
        self.assertEqual(
            delivery_time(stamp("02:00:00"), values, "liquidation"), stamp("07:00:00")
        )
        with self.assertRaises(ValueError):
            validate(
                {"use_window": True, "window_start": "01:00", "window_end": "06:00"}
            )
        overnight = validate(
            {"use_window": True, "window_start": "21:00", "window_end": "09:00"}
        )
        with patch("src.notifications.settings.random.random", return_value=0.999):
            result = delivery_time(stamp("23:00:00"), overnight, "analysis")
        self.assertFalse(quiet(result, overnight))

    def test_model_validation_and_secret_omission(self):
        values = llm_settings(
            changes={
                "mode": "custom",
                "api_base": "https://example.com/v1",
                "model": "test",
                "api_key": "secret",
                "headers": {"X-Key": "hidden"},
            }
        )
        self.assertNotIn("secret", json.dumps(llm_public(values)))
        self.assertNotIn("hidden", json.dumps(llm_public(values)))
        self.assertEqual(llm_settings(values, {"api_key": ""})["api_key"], "secret")
        for changes in (
            {"timeout": True},
            {"mode": "bad"},
            {"headers": {"X": "bad\nvalue"}},
        ):
            with self.assertRaises(ValueError):
                llm_settings(changes=changes)

    async def test_platform_route_preserves_host_context(self):
        result = await tool_loop(
            self.plugin, dict(self.game, provider="chosen"), prompt="test"
        )
        self.assertEqual(result, "platform-result")
        self.assertEqual(
            self.plugin.context.tool_loop_agent.call_args.kwargs["chat_provider_id"],
            "chosen",
        )

    async def test_recheck_blacklist_between_two_deliveries(self):
        before = stamp("23:59:00")
        after = stamp("00:01:00") + 86400
        self.engine.log(self.game, "system", "margin_call", "risk", {"level": "90"})
        self.engine.log(self.game, "human", "deposit", "funding", {"amount": "10"})
        self.service.scan(before)
        with patch(
            "src.notifications.service.time.time", side_effect=[before, before, after]
        ):
            await self.service.flush()
        self.service.send.assert_awaited_once()
        self.assertEqual(
            self.engine.db.execute(
                "SELECT count(*) FROM notice_outbox WHERE state='pending'"
            ).fetchone()[0],
            1,
        )

    def test_instance_limit_enforced_and_existing_data_kept(self):
        values = {**policy.DEFAULTS, "max_instances": 1}
        policy.update(
            self.engine, self.game["owner_id"], "用户", values, config(self.game)
        )
        with self.assertRaises(ValueError):
            self.engine.create({"user_binding": self.game["user_binding"]})
        self.assertEqual(len(self.engine.games()), 1)
        self.assertEqual(
            self.engine.get(self.game["id"])["balance"], self.game["balance"]
        )

    def test_shared_interval_minimum_and_bidirectional_state(self):
        values = {**policy.DEFAULTS, "allow_custom_interval": True}
        policy.update(
            self.engine, self.game["owner_id"], "用户", values, config(self.game)
        )
        other = self.engine.create({"user_binding": self.game["user_binding"]})
        with self.engine.transaction():
            policy.sync_interval(self.engine, self.game["owner_id"], 600)
        self.assertEqual(self.engine.users()[0]["policy"]["interval"], 600)
        for game in (self.game, other):
            saved = self.engine.get(game["id"])
            self.assertEqual(saved["interval"], 600)
            self.assertEqual(
                policy.effective(self.engine, saved)["effective_interval"], 600
            )
        with self.assertRaises(ValueError):
            policy.validate({**values, "interval": 599})

    def test_delete_user_cleans_only_owned_instances_and_revokes_id(self):
        from src.diary.store import DiaryStore
        from src.users.ownership import owner_for_token

        diary = DiaryStore(self.engine)
        original = self.engine.users()[0]
        other_instance = self.engine.create({"user_binding": self.game["user_binding"]})
        outsider = self.engine.create(
            {"user_binding": {"type": "qq", "values": ["654321"]}}
        )
        diary.enqueue(self.game["id"], "2026-11-03", "Asia/Shanghai", 0, 1, 2)
        result = self.engine.delete_virtual_user(self.game["owner_id"])
        self.assertEqual(
            set(result["deleted_instances"]), {self.game["id"], other_instance["id"]}
        )
        self.assertEqual(self.engine.get(outsider["id"])["id"], outsider["id"])
        self.assertEqual(len(self.engine.users()), 1)
        with self.assertRaises(ValueError):
            owner_for_token(self.engine.db, original["public_id"])
        with self.assertRaises(ValueError):
            self.engine.save(self.game)
        self.assertFalse(self.engine.db.execute("SELECT 1 FROM diaries").fetchone())
        self.assertFalse(self.engine.db.execute("PRAGMA foreign_key_check").fetchall())

    async def test_model_error_response_is_not_reported_as_success(self):
        self.plugin.context.tool_loop_agent.return_value=SimpleNamespace(role="err",completion_text="private-upstream-message")
        with self.assertRaises(ValueError) as caught:
            await tool_loop(self.plugin,dict(self.game,provider="chosen"),prompt="test")
        self.assertNotIn("private",str(caught.exception))
