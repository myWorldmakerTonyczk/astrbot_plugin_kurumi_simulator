"""Offline real-AstrBot diary tool loop; never calls an external provider."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astrbot.core.star.context import Context
from astrbot.core.provider.provider import Provider
from astrbot.core.provider.entities import LLMResponse, ProviderMeta
from src.core.engine import Engine
from src.users.identity import Identity
from src.diary.scheduler import DiaryService
from src.diary.settings import bounds


class ScriptedProvider(Provider):
    def __init__(self):
        super().__init__({"id": "offline-diary", "type": "offline-test"}, {})
        self.calls = []

    def get_current_key(self):
        return ""

    def set_key(self, key):
        pass

    async def get_models(self):
        return ["offline"]

    def meta(self):
        return ProviderMeta(id="offline-diary", model="offline", type="offline-test")

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        i = len(self.calls)
        if i == 1:
            return LLMResponse(
                role="assistant",
                tools_call_name=["kurumi_diary_records"],
                tools_call_args=[{"kind": "chat", "limit": 10}],
                tools_call_ids=["chat-1"],
            )
        if i == 2:
            return LLMResponse(
                role="assistant",
                tools_call_name=["kurumi_diary_past"],
                tools_call_args=[{}],
                tools_call_ids=["past-1"],
            )
        return LLMResponse(
            role="assistant",
            completion_text="今天没有急着出手，也和你聊了会儿天。把这份耐心记下来。",
        )


async def main():
    engine = Engine(":memory:")
    identity = Identity(engine)
    game = engine.create(
        {"user_binding": {"type": "umo", "values": ["bot:FriendMessage:123456"]}}
    )
    game.update(provider="offline-diary", persona="fallback")
    engine.save(game)
    provider = ScriptedProvider()
    context = Context.__new__(Context)
    context.provider_manager = SimpleNamespace(
        get_provider_by_id=AsyncMock(return_value=provider)
    )
    context.get_provider_by_id = lambda _: provider
    context.persona_manager = SimpleNamespace(
        get_persona=AsyncMock(
            return_value=SimpleNamespace(system_prompt="你是小澪，温柔俏皮。")
        )
    )
    conversation = SimpleNamespace(
        persona_id="linked-persona",
        history=json.dumps(
            [{"role": "user", "content": "FUTURE_UNDATED_PLATFORM_TEXT"}]
        ),
    )
    context.conversation_manager = SimpleNamespace(
        get_curr_conversation_id=AsyncMock(return_value="cid"),
        get_conversation=AsyncMock(return_value=conversation),
    )
    plugin = SimpleNamespace(
        engine=engine, identity=identity, context=context, settings=lambda: {}
    )
    plugin.diary = DiaryService(plugin)
    start, end = bounds("2026-11-03", "Asia/Shanghai")
    engine.db.execute("DELETE FROM logs")
    for i in range(3):
        entry = engine.log(game, "ai", "observe", "等方向清晰一些", {})
        engine.db.execute(
            "UPDATE logs SET created=?,data=json_set(data,'$.created',?) WHERE seq=?",
            (start + i, start + i, entry["id"]),
        )
    event = SimpleNamespace(
        unified_msg_origin=game["reference_umo"],
        get_sender_id=lambda: "123456",
        platform_meta=SimpleNamespace(name="aiocqhttp"),
        message_obj=SimpleNamespace(message_id="past"),
    )
    plugin.diary.store.capture(plugin, event, "user", "今天先休息一会吧", start + 50)
    event.message_obj.message_id = "future"
    plugin.diary.store.capture(plugin, event, "user", "FUTURE_ARCHIVED_TEXT", end + 1)
    plugin.diary.store.enqueue(
        game["id"], "2026-11-03", "Asia/Shanghai", start, end, end + 600
    )
    before = engine.get(game["id"])
    await plugin.diary.process_one(end + 600)
    result = plugin.diary.store.get(game["id"], "2026-11-03")
    assert result["status"] == "success", result
    assert len(provider.calls) == 3
    initial = provider.calls[0]
    assert "FUTURE_UNDATED_PLATFORM_TEXT" not in str(provider.calls)
    assert "FUTURE_ARCHIVED_TEXT" not in str(provider.calls)
    assert "今天先休息一会吧" in str(provider.calls)
    assert context.persona_manager.get_persona.call_args.args == ("linked-persona",)
    tools = initial["func_tool"]
    assert tools.get_tool("kurumi_diary_records") and tools.get_tool(
        "kurumi_diary_past"
    )
    assert not tools.get_tool("kurumi_trade")
    assert engine.get(game["id"]) == before
    assert conversation.history == json.dumps(
        [{"role": "user", "content": "FUTURE_UNDATED_PLATFORM_TEXT"}]
    )
    print(
        "Real AstrBot diary tool-loop passed: past-only chat, read-only tools, linked persona, saved diary; no trade or conversation mutations."
    )
    engine.db.close()


asyncio.run(main())
