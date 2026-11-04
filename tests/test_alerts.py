import time
import unittest
from src.core.engine import Engine
from src.core.alerts import notices


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(":memory:")
        self.g = self.e.create({"leverage": 10, "fee_rate": 0})
        self.id = self.g["id"]
        self.quote("1.1")
        self.cursor = notices(self.e, self.id)["cursor"]

    def tearDown(self):
        self.e.db.close()

    def quote(self, value):
        self.e.quotes["EUR/USD"] = dict(
            bid=value, ask=value, timestamp=time.time(), tradeable=True
        )

    def test_new_default_maximum_and_explicit_loan_rules(self):
        g = self.e.create({"loan_enabled": False, "loan_limit": 1234})
        self.assertEqual(g["leverage"], "100")
        self.assertFalse(g["loan_enabled"])
        self.assertEqual(g["loan_limit"], "1234")
        with self.assertRaises(ValueError):
            self.e.action(g["id"], "borrow", {"amount": 1})

    def test_failure_has_request_id_and_specific_cause(self):
        with self.assertRaises(ValueError):
            self.e.action(
                self.id,
                "open",
                dict(pair="EUR/USD", side="buy", units=-1),
                key="human-failed",
            )
        data = notices(self.e, self.id, self.cursor)
        self.assertEqual(len(data["events"]), 1)
        event = data["events"][0]
        self.assertEqual(event["request_id"], "human-failed")
        self.assertEqual(event["level"], "danger")
        self.assertIn("大于零", event["body"])

    def test_deposit_and_cursor_do_not_repeat(self):
        self.e.action(self.id, "deposit", {"amount": 2000})
        data = notices(self.e, self.id, self.cursor)
        self.assertIn("2,000.00", data["events"][0]["body"])
        self.assertEqual(notices(self.e, self.id, data["cursor"])["events"], [])
        self.assertEqual(notices(self.e, self.id)["events"], [])

    def test_margin_warning_only_crosses_threshold(self):
        self.e.action(self.id, "open", dict(pair="EUR/USD", side="buy", units=80000))
        self.quote("1.08")
        self.e.tick(self.id)
        self.e.tick(self.id)
        events = notices(self.e, self.id, self.cursor)["events"]
        self.assertEqual(len([e for e in events if e["action"] == "margin_call"]), 1)
        self.e.action(self.id, "deposit", {"amount": 1000})
        self.e.tick(self.id)
        self.quote("1.06")
        self.e.tick(self.id)
        events = notices(self.e, self.id, self.cursor)["events"]
        self.assertEqual(len([e for e in events if e["action"] == "margin_call"]), 2)

    def test_liquidation_and_bankruptcy_notices(self):
        self.e.action(self.id, "open", dict(pair="EUR/USD", side="buy", units=80000))
        self.quote("0.9")
        self.e.tick(self.id)
        events = notices(self.e, self.id, self.cursor)["events"]
        self.assertTrue(any("强平" in e["title"] for e in events))
        self.assertTrue(any("爆仓，本局结束" == e["title"] for e in events))
        self.assertEqual(self.e.get(self.id)["positions"], [])

    def test_pagination_scans_non_notifications_without_missing_alert(self):
        for i in range(110):
            self.e.action(self.id, "observe", {"reason": "等待"})
        self.e.action(self.id, "deposit", {"amount": 1})
        first = notices(self.e, self.id, self.cursor)
        self.assertTrue(first["has_more"])
        self.assertFalse(first["events"])
        second = notices(self.e, self.id, first["cursor"])
        self.assertEqual(len(second["events"]), 1)
        self.assertFalse(second["has_more"])

    def test_invalid_cursor_and_unknown_game(self):
        for after in [-1, "bad", True, 2**64]:
            with self.assertRaises(ValueError):
                notices(self.e, self.id, after)
        with self.assertRaises(ValueError):
            notices(self.e, "missing", 0)
