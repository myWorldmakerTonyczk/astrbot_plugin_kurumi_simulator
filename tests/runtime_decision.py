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
            assert "read_only" in str(kwargs["contexts"])
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
    game.update(status="ended", provider="offline-review", persona="test")
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
    plugin = SimpleNamespace(
        engine=engine,
        identity=identity,
        context=context,
        settings=lambda: {},
        instance_locks={},
    )
    plugin.diary = DiaryService(plugin)
    plugin.decisions = DecisionService(plugin)
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
