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

    def guard(handler, name):
        @wraps(handler)
        async def guarded(event, *args, **kwargs):
            try:
                if name not in ("kurumi_my_instances", "kurumi_select_instance"):
                    if name in ("kurumi_send_panel", "kurumi_send_review_image"):
                        owner = plugin.identity.principal(event, kwargs["user_id"])[0] if kwargs.get("user_id") else chat_owner(plugin, event)
                        if name == "kurumi_send_panel" and kwargs.get("mode", "login") == "login":
                            games = [game for game in plugin.engine.games() if game.get("owner_id") == owner]
                            if games and all(game["status"] == "paused" for game in games):
                                require_active(games[0])
                            return await handler(event, *args, **kwargs)
                        game = chat_game(plugin, event, owner, kwargs.get("instance_id", ""))
                    else:
                        game = plugin.identity.selected(event, kwargs.get("user_id", ""))
                    require_active(game)
                return await handler(event, *args, **kwargs)
            except (ValueError, TypeError) as exc:
                return dump(dict(ok=False, error=str(exc)))
        return guarded

    tools = [module.build(plugin) for module in TOOL_MODULES]
    for tool in tools:
        tool.handler = guard(tool.handler, tool.name)
    return tools


def register_tools(plugin):
    tools = build_tools(plugin)
    plugin.context.add_llm_tools(*tools)
    return tools
