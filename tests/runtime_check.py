"""Run against an installed AstrBot to check import and View auth contracts."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch, AsyncMock
import time
from astrbot.api.star import StarTools

from starlette.requests import Request
from astrbot.api.web import PluginRequest, bind_request_context

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kurumi_runtime_preview", root / "main.py", submodule_search_locations=[str(root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
engine_module = sys.modules[spec.name + ".src.engine"]
market_module = sys.modules[spec.name + ".src.market"]
temporary = TemporaryDirectory()
routes = []
registered_tools = []
context = SimpleNamespace(
    get_all_providers=lambda: [],
    persona_manager=SimpleNamespace(personas=[]),
    register_web_api=lambda *args: routes.append(args),
    add_llm_tools=lambda *tools: registered_tools.extend(tools),
)
EXPECTED_TOOLS = {
    "kurumi_forex",
    "kurumi_watch_market",
    "kurumi_read_journal",
    "kurumi_open_position",
    "kurumi_close_position",
    "kurumi_set_protection",
    "kurumi_write_memory",
    "kurumi_virtual_loan",
    "kurumi_my_instances",
    "kurumi_select_instance",
    "kurumi_write_plan",
    "kurumi_price_history",
}
with patch.object(StarTools, "get_data_dir", return_value=Path(temporary.name)):
    # Exercise both constructor signatures used by AstrBot loaders.
    plugin = module.KurumiSimulator(context)
    assert len(registered_tools) == 12
    assert {tool.name for tool in registered_tools} == EXPECTED_TOOLS
    explicit = module.KurumiSimulator(context, {})
    assert len(routes) == 14
    assert len(registered_tools) == 24
    explicit.engine.db.close()


async def check():
    for username, expected in [(None, 401), ("admin", 200)]:
        scope = dict(
            type="http",
            method="GET",
            path="/test",
            query_string=b"",
            headers=[],
            server=("test", 80),
        )
        with bind_request_context(PluginRequest(Request(scope), username=username)):
            result = await plugin.web_state()
        assert result.status_code == expected, (username, result.status_code)
        if expected == 200:
            data = json.loads(result.body)
            assert data["games"] == []
            assert "market_key" not in data["connection"]

    async def post(handler, body, username="admin"):
        raw = json.dumps(body).encode()

        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}

        scope = dict(
            type="http",
            method="POST",
            path="/test",
            query_string=b"",
            headers=[(b"content-type", b"application/json")],
            server=("test", 80),
        )
        with bind_request_context(
            PluginRequest(Request(scope, receive), username=username)
        ):
            return await handler()

    before = plugin.settings()
    with patch(
        spec.name + ".src.plugin.probe", new=AsyncMock(return_value={"ok": True})
    ) as mocked:
        result = await post(plugin.web_connection_test, {"market_source": "sina"}, None)
        assert result.status_code == 401
        mocked.assert_not_awaited()
        result = await post(plugin.web_connection_test, {"market_source": "sina"})
        assert result.status_code == 200
        assert plugin.settings() == before
        assert plugin.engine.quotes == {}
    result = await post(
        plugin.web_settings,
        {
            "market_source": "oanda",
            "market_key": "test-secret",
            "market_account": "123-456",
        },
    )
    assert result.status_code == 200
    game = plugin.engine.create({})
    plugin.engine.quotes["EUR/USD"] = dict(
        bid="1.1", ask="1.1002", timestamp=time.time(), tradeable=True
    )
    plugin.engine.action(
        game["id"], "open", dict(pair="EUR/USD", side="buy", units=1000)
    )
    result = await post(plugin.web_settings, {"market_source": "sina"})
    assert result.status_code == 400
    assert plugin.settings()["market_source"] == "oanda"
    position = plugin.engine.get(game["id"])["positions"][0]["id"]
    plugin.engine.action(game["id"], "close", dict(position=position))
    previous = plugin.engine.get(game["id"])["action_revision"]
    result = await post(plugin.web_settings, {"market_source": "sina"})
    assert result.status_code == 200
    assert plugin.engine.quotes == {}
    assert plugin.engine.get(game["id"])["action_revision"] > previous
    history_scope = dict(
        type="http",
        method="GET",
        path="/test",
        query_string=b"pair=EUR%2FUSD&period=5m&history_source=market",
        headers=[],
        server=("test", 80),
    )
    with patch.object(
        plugin.history, "page", new=AsyncMock(return_value={"bars": []})
    ) as history_page:
        with bind_request_context(
            PluginRequest(Request(history_scope), username="admin")
        ):
            response = await plugin.web_history()
        assert response.status_code == 200
        assert history_page.call_args.args[0]["history_source"] == "market"
        assert plugin.settings()["history_source"] == "frankfurter"
    for username, expected in [(None, 401), ("admin", 200)]:
        alert_scope = dict(
            type="http",
            method="GET",
            path="/test",
            query_string=("game=" + game["id"] + "&after=0").encode(),
            headers=[],
            server=("test", 80),
        )
        with bind_request_context(
            PluginRequest(Request(alert_scope), username=username)
        ):
            response = await plugin.web_alerts()
        assert response.status_code == expected
    response = await post(plugin.web_command, {"action": "create", "options": {}})
    assert response.status_code == 400
    response = await post(
        plugin.web_command,
        {
            "action": "create",
            "options": {
                "user_binding": {
                    "type": "random",
                    "values": [],
                }
            },
        },
    )
    assert response.status_code == 200
    owned = json.loads(response.body)
    assert owned["owner_name"] == "用户1"
    assert owned["user_binding"] == {"type": "random", "values": []}
    denied = await post(
        plugin.web_command, {"action": "delete", "game": owned["id"]}, None
    )
    assert denied.status_code == 401
    removed = await post(plugin.web_command, {"action": "delete", "game": owned["id"]})
    assert removed.status_code == 200
    assert plugin.engine.get(game["id"])
    race = plugin.engine.create({})

    async def delete_during_persona_lookup(_):
        plugin.engine.delete(race["id"])
        return SimpleNamespace(system_prompt="test")

    with patch.object(
        context.persona_manager,
        "get_persona",
        new=AsyncMock(side_effect=delete_during_persona_lookup),
        create=True,
    ):
        response = await post(
            plugin.web_command,
            {"action": "bind", "game": race["id"], "persona": "test", "provider": ""},
        )
    assert response.status_code == 400
    assert not any(g["id"] == race["id"] for g in plugin.engine.games())
    await plugin.initialize()
    await plugin.terminate()
    temporary.cleanup()
    print(
        "AstrBot runtime check passed: real constructors (context-only and config), 12 registered tools, lifecycle, real request context, anonymous rejection, authenticated state, secret omission, probe isolation, held-position source switching guard, stale decision invalidation."
    )


asyncio.run(check())
