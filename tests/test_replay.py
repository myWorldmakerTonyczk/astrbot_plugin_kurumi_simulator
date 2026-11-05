import time
import unittest
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from src.agent.decisions import DecisionService
from src.core.engine import Engine
from src.core.replay import review
from src.core.replay_image import CHARTS, render_png
from src.core.replay_records import decision_scope
from src.diary.store import DiaryStore


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_cash_flow_and_shared_view_excludes_private_text(self):
        engine = Engine(":memory:")
        self.addCleanup(engine.db.close)
        game = engine.create({})
        gid = game["id"]
        plugin = SimpleNamespace(engine=engine, settings=lambda: {})
        DiaryStore(engine)
        decisions = DecisionService(plugin)
        engine.action(gid, "deposit", {"amount": "500"})
        job = decisions.enqueue(gid, "定时看盘")
        engine.quotes["EUR/USD"] = dict(bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True)
        scope = decision_scope.set((gid, job))
        try:
            engine.action(gid, "open", {"pair": "EUR/USD", "side": "buy", "units": "1000", "reason": "私人操作理由"}, "ai")
        finally:
            decision_scope.reset(scope)
        engine.action(gid, "plan", {"text": "私人策略", "reason": "复盘"}, "ai")
        engine.db.execute("UPDATE decision_jobs SET state='success', result=? WHERE id=?", ('{"summary":"私人摘要"}', job))
        private = await review(plugin, gid, include_candles=False)
        self.assertIn("私人策略", [event["text"] for event in private["events"]])
        self.assertEqual(next(event for event in private["events"] if event["action"] == "review")["outcome"], "已成交")
        self.assertAlmostEqual(private["marks"][-1]["return_rate"], 0, delta=.01)
        shared = await review(plugin, gid, private=False, include_candles=False)
        self.assertEqual([event["action"] for event in shared["events"]], ["open"])
        self.assertNotIn("私人", str(shared))
        self.assertEqual(shared["diaries"], [])
        self.assertEqual(shared["events"][0]["reason"], "")

    def test_all_chart_types_generate_png(self):
        now = int(time.time())
        event = dict(
            time=now - 300, action="close", status="success", price=1.12,
            actor="system", position={"side": "buy", "pnl": "2.5"}, fee=.1,
        )
        data = dict(
            days=1, start=now - 86400, end=now, pair="EUR/USD", events=[
                event, dict(time=now - 400, action="review", status="failed")
            ],
            marks=[dict(time=now - 800, equity=10000, return_rate=0, drawdown=0),
                   dict(time=now - 200, equity=9900, return_rate=-1, drawdown=1)],
            candles=[dict(time=now - 400, open=1.11, high=1.13, low=1.10, close=1.12)],
        )
        for kind in CHARTS:
            with self.subTest(kind=kind):
                with Image.open(BytesIO(render_png(data, kind))) as image:
                    self.assertEqual(image.format, "PNG")
                    image.verify()
