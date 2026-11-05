"""Real AstrBot tool loop for a queued, ended-account risk review, fully offline."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astrbot.core.star.context import Context
from astrbot.core.provider.provider import Provider
from astrbot.core.provider.entities import ProviderMeta, LLMResponse
from src.core.engine import Engine
from src.users.identity import Identity
from src.diary.scheduler import DiaryService
from src.agent.decisions import DecisionService
from src.agent.runner import reference_context


class OfflineProvider(Provider):
    def __init__(self):
        super().__init__({"id": "offline-review", "type": "offline-test"}, {})
        self.calls = 0

    def get_current_key(self):
        return ""

    def set_key(self, key):
        pass

    async def get_models(self):
        return ["offline"]

    def meta(self):
        return ProviderMeta(id="offline-review", model="offline", type="offline-test")

    async def text_chat(self, **kwargs):
        self.calls += 1
        tools = kwargs["func_tool"]
        assert tools.get_tool("kurumi_trade") is None
        assert tools.get_tool("kurumi_write_plan") is None
        assert tools.get_tool("kurumi_set_notifications") is None
        if self.calls == 1:
            context = str(kwargs["contexts"])
            assert "read_only" in context
            assert "近期用户发言" in context and "近期助手回复" in context
            assert "较早用户发言" not in context
            return LLMResponse(
                role="assistant",
                tools_call_name=["kurumi_watch_market"],
                tools_call_args=[{}],
                tools_call_ids=["state-1"],
            )
        return LLMResponse(
            role="assistant", completion_text="本局已经结束，只复盘，不再开仓。"
        )


async def main():
    engine = Engine(":memory:")
    identity = Identity(engine)
    game = engine.create(
        {"user_binding": {"type": "umo", "values": ["bot:FriendMessage:123456"]}}
    )
    game.update(status="ended", provider="offline-review", persona="test", history_count=2)
    engine.save(game)
    provider = OfflineProvider()
    context = Context.__new__(Context)
    context.provider_manager = SimpleNamespace(
        get_provider_by_id=AsyncMock(return_value=provider)
    )
    context.get_provider_by_id = lambda _: provider
    context.persona_manager = SimpleNamespace(
        get_persona=AsyncMock(return_value=SimpleNamespace(system_prompt="你是小澪。"))
    )
    context.conversation_manager = SimpleNamespace(
        get_curr_conversation_id=AsyncMock(return_value="cid"),
        get_conversation=AsyncMock(return_value=SimpleNamespace(history=[
            {"role": "user", "content": "较早用户发言"},
            {"role": "user", "content": [{"type": "text", "text": "近期用户发言"}]},
            {"role": "tool", "content": "工具结果"},
            {"role": "assistant", "content": "近期助手回复"},
        ], persona_id="test")),
    )
    plugin = SimpleNamespace(
        engine=engine,
        identity=identity,
        context=context,
        settings=lambda: {},
        instance_locks={},
    )
    plugin.diary = DiaryService(plugin)
    plugin.decisions = DecisionService(plugin)
    umo = game["reference_umo"]
    engine.db.execute(
        "INSERT INTO diary_chat(game,umo,message_id,role,content,created) VALUES(?,?,?,?,?,?)",
        (game["id"], umo, "1", "user", "归档聊天", time.time()),
    )
    context.conversation_manager.get_curr_conversation_id.return_value = None
    rows, _, _ = await reference_context(plugin, game)
    assert rows == [{"role": "user", "content": "归档聊天"}]
    rows, _, _ = await reference_context(plugin, dict(game, history_count=0))
    assert rows == []
    context.conversation_manager.get_curr_conversation_id.return_value = "cid"

    engine.log(game, "system", "end", "触发游戏结束条件", {"bankrupt": True})
    now = time.time()
    plugin.decisions.scan(now)
    assert plugin.decisions.state(game["id"], now)["state"] == "pending"
    await plugin.decisions.process_one(now)
    result = plugin.decisions.state(game["id"], now)
    assert result["state"] == "success", result
    assert "只复盘" in result["last_summary"]
    assert provider.calls == 2
    assert engine.get(game["id"])["positions"] == []
    assert engine.get(game["id"])["status"] == "ended"
    plugin.decisions.request_manual(game["id"], now + 1)
    assert not await plugin.decisions.process_one(now + 1)
    assert provider.calls == 2
    print(
        "Real queued risk-review passed: trigger -> queue -> LLM -> read-only tool -> summary; ended account unchanged, manual retry rate-limited."
    )
    engine.db.close()


asyncio.run(main())
