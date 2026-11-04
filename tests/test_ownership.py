import tempfile
import time
import unittest
from pathlib import Path
from src.engine import Engine
from src.ownership import normalize


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(":memory:")

    def tearDown(self):
        self.e.db.close()

    def make(self, kind="umo", values=None, nickname="", **extra):
        binding = dict(type=kind, values=values or ["default:FriendMessage:123456789"])
        binding.update(extra)
        return self.e.create(dict(user_binding=binding, user_nickname=nickname))

    def test_incrementing_names_and_reused_owner(self):
        a = self.make()
        b = self.make()
        c = self.make("qq", ["123456"])
        self.assertEqual(a["owner_name"], "用户1")
        self.assertEqual(a["owner_id"], b["owner_id"])
        self.assertEqual(c["owner_name"], "用户2")
        self.assertEqual(len(self.e.users()), 2)

    def test_nickname_and_umo_aliases(self):
        a = self.make(
            values=["robot-a:FriendMessage:123456", "robot-b:FriendMessage:123456"],
            nickname="小鱼",
        )
        b = self.make(values=["robot-b:FriendMessage:123456"])
        self.assertEqual(a["owner_id"], b["owner_id"])
        self.assertEqual(b["owner_name"], "小鱼")

    def test_conflicting_aliases_rejected_without_creating_game(self):
        self.make(values=["a:FriendMessage:123456"])
        self.make(values=["b:FriendMessage:123456"])
        count = len(self.e.games())
        with self.assertRaises(ValueError):
            self.make(values=["a:FriendMessage:123456", "b:FriendMessage:123456"])
        self.assertEqual(len(self.e.games()), count)
        self.assertEqual(len(self.e.users()), 2)

    def test_invalid_binding(self):
        for binding in [
            None,
            {},
            dict(type="qq", values=["abc"]),
            dict(type="umo", values=["a:GroupMessage:12345"]),
            dict(type="umo", values=["bad"]),
            dict(type="umo", values=[]),
            dict(type="account", values=["abc"], password="short"),
        ]:
            with self.assertRaises(ValueError):
                normalize(binding)

    def test_random_id_reuse_and_rotation(self):
        a = self.e.create({"user_binding": {"type": "random", "values": []}})
        token = self.e.users()[0]["public_id"]
        b = self.e.create({"user_binding": {"type": "random", "values": [token]}})
        self.assertEqual(a["owner_id"], b["owner_id"])
        new = self.e.rotate_user_id(a["owner_id"])["public_id"]
        self.assertNotEqual(token, new)
        with self.assertRaises(ValueError):
            self.e.create({"user_binding": {"type": "random", "values": [token]}})
        c = self.e.create({"user_binding": {"type": "random", "values": [new]}})
        self.assertEqual(c["owner_id"], a["owner_id"])
        self.assertEqual(a["user_binding"]["values"], [])

    def test_admin_user_generation_has_unique_ids(self):
        first = self.e.create_virtual_user()
        second = self.e.create_virtual_user()
        self.assertNotEqual(first["public_id"], second["public_id"])
        self.assertEqual(first["name"], "用户1")
        self.assertEqual(second["name"], "用户2")
        self.assertEqual(self.e.games(), [])

    def test_default_name_counter_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            a = Engine(path)
            first = a.create({"user_binding": {"type": "qq", "values": ["123456"]}})
            a.delete(first["id"])
            a.db.close()
            b = Engine(path)
            second = b.create({"user_binding": {"type": "qq", "values": ["223456"]}})
            self.assertEqual(second["owner_name"], "用户2")
            b.db.close()


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(":memory:")

    def tearDown(self):
        self.e.db.close()

    def test_delete_only_target_ledger_and_preserve_user(self):
        options = {"user_binding": {"type": "qq", "values": ["123456"]}}
        first = self.e.create(options)
        other = self.e.create(options)
        self.e.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
        )
        self.e.action(first["id"], "open", dict(pair="EUR/USD", side="buy", units=100))
        self.e.action(first["id"], "notes", {"text": "private notes"})
        stale = self.e.get(first["id"])
        other_before = self.e.get(other["id"])
        self.e.delete(first["id"])
        with self.assertRaises(ValueError):
            self.e.get(first["id"])
        with self.assertRaises(ValueError):
            self.e.save(stale)
        self.assertEqual(self.e.logs(first["id"]), [])
        self.assertEqual(
            self.e.db.execute(
                "SELECT count(*) FROM requests WHERE game=?", (first["id"],)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.e.get(other["id"]), other_before)
        self.assertEqual(len(self.e.users()), 1)
        self.assertTrue(self.e.quotes)

    def test_unknown_delete_does_not_touch_other_instance(self):
        game = self.e.create({})
        with self.assertRaises(ValueError):
            self.e.delete("not-an-instance")
        self.assertEqual(self.e.get(game["id"]), game)
