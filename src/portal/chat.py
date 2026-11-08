"""Resolve chat-originated portal requests using trusted private message events."""

from ..diary.store import redact


def chat_owner(plugin, event):
    if getattr(getattr(event, "platform_meta", None), "name", "") == "kurumi_silent":
        raise ValueError("请在已绑定的私聊领取面板")
    # Delegated portal_chat grants remain stored for future use, but the current
    # UI only supports the instance owner's independently bound private chat.
    plugin.identity.event_scope(event)
    try:
        return plugin.identity.principal(event)[0]
    except ValueError as exc:
        raise ValueError("请在实例所属用户已绑定的私聊中领取面板") from exc


def chat_game(plugin, event, owner, instance_id=""):
    _, _, scope = plugin.identity.event_scope(event)
    games = [game for game in plugin.engine.games() if game.get("owner_id") == owner]
    if not games:
        raise ValueError("当前用户还没有交易实例")
    if instance_id:
        if not isinstance(instance_id, str) or len(instance_id) > 64:
            raise ValueError("实例编号无效")
        if instance_id.isascii() and instance_id.isdigit() and 1 <= int(instance_id) <= len(games):
            return games[int(instance_id) - 1]
        for game in games:
            if game["id"] == instance_id:
                return game
        raise ValueError("实例不存在或不属于当前用户")
    if len(games) == 1:
        return games[0]
    selection = plugin.engine.db.execute(
        "SELECT instance_id FROM sim_selections WHERE scope=? AND user_id=?", (scope, owner)
    ).fetchone()
    if selection:
        for game in games:
            if game["id"] == selection[0]:
                return game
    choices = "；".join(f"{i} {redact(game['name'])}" for i, game in enumerate(games[:20], 1))
    raise ValueError("有多个实例，请选择实例序号：" + choices)
