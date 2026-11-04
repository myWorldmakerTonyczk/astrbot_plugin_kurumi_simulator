import time
import unittest
from unittest.mock import patch
from decimal import Decimal
from src.core.engine import Engine, number, loan_debt


class LoanTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(":memory:")
        self.e.quotes["EUR/USD"] = dict(
            bid="1.1", ask="1.1", timestamp=time.time(), tradeable=True
        )
        self.g = self.e.create({"fee_rate": 0, "leverage": 10})
        self.gid = self.g["id"]

    def tearDown(self):
        self.e.db.close()

    def test_borrow_net_wealth_and_capacity(self):
        with patch("src.core.engine.time.time", return_value=self.g["loan_last"]):
            self.e.action(self.gid, "borrow", {"amount": 5000, "reason": "周转"}, "ai")
            g = self.e.get(self.gid)
            v = self.e.valuation(g)
            self.assertEqual(number(v["equity"]), 10000)
            self.assertEqual(number(v["free"]), 15000)
            self.assertEqual(number(v["profit"]), 0)
            self.assertEqual(number(g["invested"]), 10000)
            self.e.action(
                self.gid,
                "open",
                dict(pair="EUR/USD", side="buy", margin=12000, leverage=10),
            )
            self.assertEqual(
                number(self.e.valuation(self.e.get(self.gid))["margin"]), 12000
            )

    def test_repay_preserves_net_wealth(self):
        with patch("src.core.engine.time.time", return_value=self.g["loan_last"]):
            self.e.action(self.gid, "borrow", {"amount": 5000})
            self.e.action(self.gid, "repay", {"amount": 1000})
            v = self.e.valuation(self.e.get(self.gid))
            self.assertEqual(number(v["equity"]), 10000)
            self.assertEqual(number(v["debt"]), 4000)

    def test_cap_and_permissions(self):
        with self.assertRaises(ValueError):
            self.e.action(self.gid, "borrow", {"amount": 20001})
        self.e.action(self.gid, "loan_config", {"enabled": False})
        with self.assertRaises(ValueError):
            self.e.action(self.gid, "borrow", {"amount": 1, "reason": "借款"}, "ai")
        with self.assertRaises(ValueError):
            self.e.action(
                self.gid, "loan_config", {"enabled": True, "reason": "自行开启"}, "ai"
            )
        with self.assertRaises(ValueError):
            self.e.create({"loan_enabled": "false"})

    def test_daily_interest_and_interest_first_repayment(self):
        start = self.g["loan_last"]
        with patch("src.core.engine.time.time", return_value=start):
            self.e.action(self.gid, "borrow", {"amount": 10000})
        with patch("src.core.engine.time.time", return_value=start + 86400):
            self.assertEqual(loan_debt(self.e.get(self.gid)), Decimal("10001"))
            self.e.action(self.gid, "repay", {"amount": 1})
            g = self.e.get(self.gid)
            self.assertEqual(number(g["loan_principal"]), 10000)
            self.assertEqual(number(g["loan_interest"]), 0)
            self.assertEqual(number(g["loan_cost"]), 1)
            self.assertEqual(number(self.e.valuation(g)["equity"]), 9999)

    def test_ended_game_debt_frozen(self):
        g = dict(self.g, loan_principal="1000", loan_last=100, status="ended")
        self.assertEqual(loan_debt(g, 1000000), 1000)

    def test_leverage_per_position_and_cap(self):
        self.e.action(
            self.gid, "open", dict(pair="EUR/USD", side="buy", margin=100, leverage=2)
        )
        g = self.e.get(self.gid)
        self.assertEqual(g["positions"][0]["leverage"], "2")
        self.assertEqual(number(self.e.valuation(g)["margin"]), 100)
        self.e.action(self.gid, "close", {"position": g["positions"][0]["id"]})
        with self.assertRaises(ValueError):
            self.e.action(
                self.gid,
                "open",
                dict(pair="EUR/USD", side="buy", units=100, leverage=11),
            )

    def test_insufficient_repay_atomic(self):
        with patch("src.core.engine.time.time", return_value=self.g["loan_last"]):
            self.e.action(self.gid, "borrow", {"amount": 10000})
            self.e.action(
                self.gid, "open", dict(pair="EUR/USD", side="buy", margin=15000)
            )
            before = self.e.get(self.gid)
            with self.assertRaises(ValueError):
                self.e.action(self.gid, "repay", {"amount": 10000})
            after = self.e.get(self.gid)
            self.assertEqual(before, after)
