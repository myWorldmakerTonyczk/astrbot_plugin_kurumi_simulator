"""Use the real SDK with a local HTTP mock; never contacts a model service."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from astrbot.core.star.context import Context
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from src.agent.llm import tool_loop, public
from src.agent.runner import silent_event
from src.notifications.service import NotificationService


async def main():
    requests = []
    clients = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            message = dict(
                role="assistant",
                content=None,
                tool_calls=[
                    dict(
                        id="read-1",
                        type="function",
                        function=dict(name="read_test", arguments="{}"),
                    )
                ],
            )
            finish = "tool_calls"
        else:
            message = dict(role="assistant", content="custom tool loop complete")
            finish = "stop"
        return httpx.Response(
            200,
            json=dict(
                id="offline-1",
                object="chat.completion",
                created=1,
                model="offline-model",
                choices=[dict(index=0, message=message, finish_reason=finish)],
                usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
        )

    class OfflineOpenAI(ProviderOpenAIOfficial):
        def _create_http_client(self, config):
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            clients.append(client)
            return client

    async def read(_event):
        return '{"virtual_balance":"10000"}'

    host = Context.__new__(Context)
    original_manager = SimpleNamespace()
    host.provider_manager = original_manager
    config = dict(
        mode="custom",
        debug_prompt=True,
        api_base="https://offline.invalid/v1",
        model="offline-model",
        api_key="secret-test",
        headers={"X-Test": "header-test"},
    )
    plugin = SimpleNamespace(context=host, settings=lambda: {"llm": config})
    game = dict(
        id="offline-instance", provider="", reference_umo="bot:FriendMessage:123456"
    )
    with (
        patch(
            "astrbot.core.provider.sources.openai_source.ProviderOpenAIOfficial",
            OfflineOpenAI,
        ),
        patch("astrbot.api.logger.info") as debug_logs,
    ):
        response = await tool_loop(
            plugin,
            game,
            event=silent_event(game),
            prompt="Read test balance.",
            tools=ToolSet(
                [
                    FunctionTool(
                        name="read_test",
                        description="Read-only local test",
                        parameters=dict(type="object", properties={}),
                        handler=read,
                    )
                ]
            ),
            max_steps=3,
        )
    logged = str(debug_logs.call_args_list)
    assert "Read test balance." in logged
    assert "secret-test" not in logged
    assert "header-test" not in logged
    assert response.completion_text == "custom tool loop complete"
    assert len(requests) == 2
    assert str(requests[0].url) == "https://offline.invalid/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer secret-test"
    assert requests[0].headers["x-test"] == "header-test"
    assert json.loads(requests[0].content)["model"] == "offline-model"
    assert "virtual_balance" in requests[1].content.decode()
    assert host.provider_manager is original_manager
    assert all(client.is_closed for client in clients)
    assert "secret-test" not in json.dumps(public(config))
    # Exercise the real MessageChain API against a local mocked delivery function.
    service = NotificationService.__new__(NotificationService)
    service.plugin = SimpleNamespace(
        context=SimpleNamespace(send_message=AsyncMock(return_value=True))
    )
    await service.send("bot:FriendMessage:123456", "offline delivery test")
    assert service.plugin.context.send_message.await_count == 1
    print(
        "Custom OpenAI-compatible tool loop passed: private provider, headers/key/model, real tool execution, client cleanup, host unchanged; MessageChain delivery API passed."
    )


asyncio.run(main())
