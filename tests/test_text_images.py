"""Text and diary image rendering, including the chat delivery path."""
import json
import sys
import types
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from PIL import Image
from src.core.engine import Engine
from src.core.replay_image import render_chart_sheet, render_text_png
from src.tools.send_review_image import build
from src.users.identity import Identity
from src.users.tool_access import CURRENT


class TextImageTests(unittest.IsolatedAsyncioTestCase):
    def test_long_text_is_bounded_and_mixed_sheet_preserves_full_panel(self):
        panel=dict(title="交易日记",subtitle="2026-11-08",content="今天先看看，不急嘛\n"*3000)
        with Image.open(BytesIO(render_text_png(panel))) as image:
            self.assertLessEqual(image.height,8838)
            self.assertEqual(image.width,1120)
        data=dict(text_panels={"diary":dict(panel,content="等它站稳再说呀\n"*50)},days=1,start=1,end=100,pair="EUR/USD",events=[],marks=[],candles=[])
        with Image.open(BytesIO(render_chart_sheet(data,["equity","return","diary"]))) as image:
            self.assertEqual(image.width,2312)
            self.assertGreater(image.height,2000)

    async def test_send_diary_text_and_combined_images(self):
        engine=Engine(":memory:")
        self.addCleanup(engine.db.close)
        identity=Identity(engine)
        game=engine.create({"user_binding":{"type":"umo","values":["bot:FriendMessage:1"]}})
        rows=Mock(return_value=[dict(day="2026-11-08",content="今天鱼先不急着下单呀\n等收盘站稳再说")])
        plugin=SimpleNamespace(engine=engine,identity=identity,diary=SimpleNamespace(store=SimpleNamespace(list=rows)))
        event=SimpleNamespace(unified_msg_origin="bot:FriendMessage:1",get_sender_id=lambda:"1",send=AsyncMock())
        toolmodule=types.ModuleType("astrbot.core.agent.tool")
        toolmodule.FunctionTool=type("FunctionTool",(),{"__init__":lambda self,**kw:self.__dict__.update(kw)})
        events=types.ModuleType("astrbot.api.event")
        events.MessageChain=lambda **kw:SimpleNamespace(**kw)
        components=types.ModuleType("astrbot.api.message_components")
        components.Image=SimpleNamespace(fromBytes=lambda value:value)
        projection=dict(days=1,start=1,end=100,pair="EUR/USD",events=[],marks=[],candles=[])
        with patch.dict(sys.modules,{"astrbot.core.agent.tool":toolmodule,"astrbot.api.event":events,"astrbot.api.message_components":components}),patch("src.tools.send_review_image.review",AsyncMock(return_value=projection)):
            tool=build(plugin)
            token=CURRENT.set(game["id"])
            try:
                result=json.loads(await tool.handler(event,kind="diary",diary_date="2026-11-08"))
                self.assertTrue(result["ok"])
                self.assertEqual(rows.call_args.args[1],"2026-11-09")
                result=json.loads(await tool.handler(event,kinds=["text","equity"],text="哼，等它回来再说"))
                self.assertTrue(result["ok"])
                result=json.loads(await tool.handler(event,kind="text",text=""))
                self.assertFalse(result["ok"])
                self.assertEqual(event.send.await_count,2)
                for call in event.send.await_args_list:
                    with Image.open(BytesIO(call.args[0].chain[0])) as image:
                        image.verify()
            finally:
                CURRENT.reset(token)
