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
engine_module = sys.modules[spec.name + ".src.core.engine"]
market_module = sys.modules[spec.name + ".src.market_data.market"]
temporary = TemporaryDirectory()
routes = []
registered_tools = []
context = SimpleNamespace(
    get_all_providers=lambda: [],
    get_provider_by_id=lambda pid: SimpleNamespace() if pid=="test" else None,
    persona_manager=SimpleNamespace(personas=[SimpleNamespace(persona_id="test")], get_persona=AsyncMock(return_value=SimpleNamespace(persona_id="test"))),
    register_web_api=lambda *args: routes.append(args),
    add_llm_tools=lambda *tools: registered_tools.extend(tools),
)
EXPECTED_TOOLS = {
    "kurumi_forex",
    "kurumi_watch_market",
    "kurumi_read_journal",
    "kurumi_read_diary",
    "kurumi_open_position",
    "kurumi_close_position",
    "kurumi_set_protection",
    "kurumi_set_notifications",
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
    assert len(registered_tools) == 14
    assert {tool.name for tool in registered_tools} == EXPECTED_TOOLS
    explicit = module.KurumiSimulator(context, {})
    assert len(routes) == 24
    assert len(registered_tools) == 28
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

    assert (await post(plugin.web_llm_settings, {"mode":"custom","api_base":"https://example.com/v1","model":"test"}, None)).status_code==401
    assert (await post(plugin.web_llm_settings, {"mode":"custom","api_base":"https://example.com/v1","model":"test","api_key":"private-llm-key","headers":{"X-Secret":"private-header"}})).status_code==200
    public_scope=dict(type="http",method="GET",path="/test",query_string=b"",headers=[],server=("test",80))
    with bind_request_context(PluginRequest(Request(public_scope),username="admin")):
        public_state=await plugin.web_state()
    assert "private-llm-key" not in public_state.body.decode()
    assert "private-header" not in public_state.body.decode()
    assert (await post(plugin.web_llm_settings, {"mode":"platform","provider_id":"test"})).status_code==200
    diary_before = plugin.diary.config()
    result = await post(plugin.web_diary_settings, {"min_logs": 5}, None)
    assert result.status_code == 401
    assert plugin.diary.config() == diary_before
    result = await post(plugin.web_diary_settings, {"min_logs": -1})
    assert result.status_code == 400
    result = await post(plugin.web_diary_settings, {"min_logs": 5, "chat_only": True})
    assert result.status_code == 200
    assert plugin.diary.config()["min_logs"] == 5
    assert plugin.diary.config()["chat_only"] is True
    before = plugin.settings()
    with patch(
        spec.name + ".src.integration.plugin.probe", new=AsyncMock(return_value={"ok": True})
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
    # Missing/unknown personas must fail without creating games or users.
    before_games = len(plugin.engine.games())
    for persona in (None, "", "deleted-persona"):
        invalid = await post(plugin.web_command, {"action": "create", "options": {"user_binding": {"type": "random", "values": []}, "persona": persona}})
        assert invalid.status_code == 400
    assert len(plugin.engine.games()) == before_games
    values = plugin.settings()
    values["llm"] = {"mode": "platform", "provider_id": "test"}
    plugin.engine.db.execute("UPDATE settings SET data=? WHERE id=1", (json.dumps(values),))
    response = await post(
        plugin.web_command,
        {
            "action": "create",
            "options": {
                "persona": "test",
                "user_binding": {
                    "type": "random",
                    "values": [],
                }
            },
        },
    )
    assert response.status_code == 200
    owned = json.loads(response.body)
    assert owned["auto"] is True and owned["persona"] == "test"
    invalid = await post(plugin.web_command, {"action": "bind", "game": owned["id"], "persona": "", "auto": False})
    assert invalid.status_code == 400
    # An instance request cannot bypass the administrator-owned interval lock.
    denied_interval=await post(plugin.web_command,{"action":"bind","game":owned["id"],"interval":7200})
    assert denied_interval.status_code==400
    user=plugin.engine.users()[0]
    revised=dict(user["policy"],allow_custom_interval=True,interval=3600,allow_panel_notice=False,allow_tool_notice=False)
    assert (await post(plugin.web_command,{"action":"update_user","user_id":user["id"],"nickname":"新昵称","policy":revised,"notifications":user["notifications"]},None)).status_code==401
    updated=await post(plugin.web_command,{"action":"update_user","user_id":user["id"],"nickname":"新昵称","policy":revised,"notifications":user["notifications"]})
    assert updated.status_code==200
    allowed_interval=await post(plugin.web_command,{"action":"bind","game":owned["id"],"interval":7200})
    assert allowed_interval.status_code==200
    assert plugin.engine.get(owned["id"])["interval"]==7200
    assert next(u for u in plugin.engine.users() if u["id"]==user["id"])["policy"]["interval"]==7200
    assert (await post(plugin.web_command,{"action":"bind","game":owned["id"],"interval":599})).status_code==400
    assert (await post(plugin.web_decision_settings,{"cooldown":600},None)).status_code==401
    assert (await post(plugin.web_decision_settings,{"cooldown":599})).status_code==400
    assert (await post(plugin.web_decision_settings,{"cooldown":600,"hourly_limit":6})).status_code==200
    plugin.engine.quotes["EUR/USD"]=dict(bid="1.1",ask="1.1002",timestamp=time.time(),tradeable=True)
    assert (await post(plugin.web_decision,{"game":owned["id"]},None)).status_code==401
    queued=await post(plugin.web_decision,{"game":owned["id"]})
    assert queued.status_code==200
    job=json.loads(queued.body)["decision"]["job_id"]
    duplicate=await post(plugin.web_decision,{"game":owned["id"]})
    assert json.loads(duplicate.body)["decision"]["job_id"]==job
    plugin.decisions.runner=AsyncMock(return_value={"summary":"离线接口复盘完成"})
    await plugin.decisions.process_one()
    assert plugin.decisions.runner.await_count==1
    assert plugin.decisions.state(owned["id"])["state"]=="success"
    denied_notice=await post(plugin.web_command,{"action":"notifications","game":owned["id"],"settings":{"enabled":False}})
    assert denied_notice.status_code==400
    assert owned["owner_name"] == "用户1"
    assert owned["user_binding"] == {"type": "random", "values": []}
    denied = await post(
        plugin.web_command, {"action": "delete", "game": owned["id"]}, None
    )
    assert denied.status_code == 401
    removed = await post(plugin.web_command, {"action": "delete", "game": owned["id"]})
    assert removed.status_code == 200
    assert (await post(plugin.web_command,{"action":"delete_user","user_id":owned["owner_id"]},None)).status_code==401
    assert (await post(plugin.web_command,{"action":"delete_user","user_id":owned["owner_id"]})).status_code==200
    assert plugin.engine.get(game["id"])
    archive_game = plugin.engine.create({"user_binding": {"type": "umo", "values": ["archive:FriendMessage:123456"]}})
    event = SimpleNamespace(unified_msg_origin="archive:FriendMessage:123456", get_sender_id=lambda: "123456",
                            platform_meta=SimpleNamespace(name="aiocqhttp"), message_obj=SimpleNamespace(message_id="archive-hook"),
                            get_message_str=lambda: "今天先聊聊天", get_result=lambda: SimpleNamespace(chain=[SimpleNamespace(text="好呀，慢慢聊")]))
    await plugin.trading_context(event, SimpleNamespace(system_prompt=""))
    await plugin.diary_reply_sent(event)
    archived = plugin.engine.db.execute("SELECT role,content FROM diary_chat WHERE game=? ORDER BY seq", (archive_game["id"],)).fetchall()
    assert [row["role"] for row in archived] == ["user", "assistant"]
    plugin.engine.delete(archive_game["id"])
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
        "AstrBot runtime check passed: real constructors (context-only and config), 14 registered tools, lifecycle, real request context, anonymous rejection, authenticated state, secret omission, probe isolation, held-position source switching guard, stale decision invalidation."
    )


asyncio.run(check())
