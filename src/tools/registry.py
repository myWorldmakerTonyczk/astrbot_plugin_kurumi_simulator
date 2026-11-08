"""Central registry that installs every chat-facing kurumi tool."""

from . import (
    close_position,
    forex,
    my_instances,
    open_position,
    price_history,
    read_journal,
    read_diary,
    send_review_image,
    send_panel,
    select_instance,
    set_protection,
    set_notifications,
    virtual_loan,
    watch_market,
    write_memory,
    write_plan,
)

TOOL_MODULES = (
    forex,
    watch_market,
    read_journal,
    read_diary,
    open_position,
    close_position,
    set_protection,
    set_notifications,
    write_memory,
    virtual_loan,
    my_instances,
    select_instance,
    write_plan,
    price_history,
    send_review_image,
    send_panel,
)


def build_tools(plugin):
    from ..core.availability import require_active
    from ..core.engine import dump
    from ..portal.chat import chat_game, chat_owner

    from functools import wraps

    from ..users.tool_access import CURRENT, available, is_read, resolve
    import inspect

    def guard(handler, name):
        accepts_instance = "instance_id" in inspect.signature(handler).parameters
        @wraps(handler)
        async def guarded(event, *args, **kwargs):
            token = None
            try:
                if name == "kurumi_send_panel":
                    # Login credentials and one-time links stay in the bound private chat.
                    owner = chat_owner(plugin, event)
                    try:
                        selected = chat_game(plugin, event, owner, kwargs.get("instance_id", ""))
                    except ValueError:
                        games = [g for g in plugin.engine.games() if g.get("owner_id") == owner]
                        if games and all(g["status"] == "paused" for g in games):
                            require_active(games[0])
                    else:
                        require_active(selected)
                    return await handler(event, *args, **kwargs)
                read = None if name == "kurumi_select_instance" else is_read(name, kwargs)
                if name == "kurumi_my_instances":
                    games = available(plugin, event, None)
                    return dump(dict(ok=True, instances=[dict(id=g["id"], name=g["name"], status=g["status"]) for g in games]))
                instance = kwargs.get("instance_id", "")
                game = resolve(plugin, event, read, instance)
                if name == "kurumi_select_instance":
                    try:
                        owner = plugin.identity.principal(event)[0]
                    except ValueError:
                        owner = None
                    if owner == game.get("owner_id"):
                        plugin.identity.select(event, game["id"])
                    scope = str(event.unified_msg_origin) + "\x1f" + str(event.get_sender_id())
                    plugin.engine.db.execute("CREATE TABLE IF NOT EXISTS shared_tool_selection(scope TEXT PRIMARY KEY,game TEXT NOT NULL)")
                    plugin.engine.db.execute("INSERT OR REPLACE INTO shared_tool_selection VALUES(?,?)", (scope, game["id"]))
                    return dump(dict(ok=True, instance=dict(id=game["id"], name=game["name"])))
                require_active(game)
                token = CURRENT.set(game["id"])
                if not accepts_instance:
                    kwargs.pop("instance_id", None)
                return await handler(event, *args, **kwargs)
            except (ValueError, TypeError) as exc:
                return dump(dict(ok=False, error=str(exc)))
            finally:
                if token is not None:
                    CURRENT.reset(token)
        return guarded

    tools = [module.build(plugin) for module in TOOL_MODULES]
    for tool in tools:
        if tool.name != "kurumi_send_panel":
            tool.parameters = dict(tool.parameters, properties=dict(tool.parameters["properties"]))
            tool.parameters["properties"].setdefault("instance_id", dict(type="string", description="目标实例 ID 或可访问实例列表中的序号，多实例时填写"))
        tool.handler = guard(tool.handler, tool.name)
    return tools


def register_tools(plugin):
    tools = build_tools(plugin)
    plugin.context.add_llm_tools(*tools)
    return tools
