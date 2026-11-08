"""Resolve per-instance permissions from the trusted incoming chat."""
from contextvars import ContextVar
from .policy import for_user

CURRENT = ContextVar("kurumi_authorized_instance", default=None)
READ_TOOLS = {"kurumi_watch_market", "kurumi_read_journal", "kurumi_read_diary",
              "kurumi_price_history", "kurumi_send_review_image",
              "kurumi_my_instances", "kurumi_select_instance"}


def is_read(name, kwargs):
    if name != "kurumi_forex":
        return name in READ_TOOLS
    return kwargs.get("action") in {"state", "logs", "history", "diary"}


def permitted(plugin, event, game, read):
    if getattr(getattr(event, "platform_meta", None), "name", "") == "kurumi_silent":
        return False
    umo = str(event.unified_msg_origin)
    parts = umo.split(":")
    if len(parts) != 3 or parts[1] not in ("FriendMessage", "GroupMessage") or not str(event.get_sender_id()):
        return False
    try:
        owner = plugin.identity.principal(event)[0] if parts[1] == "FriendMessage" else None
    except ValueError:
        owner = None
    if owner and owner == game.get("owner_id"):
        return True
    policy = for_user(plugin.engine.db, game.get("owner_id", ""))
    prefix = "group" if parts[1] == "GroupMessage" else "foreign"
    return bool(game.get("owner_id") and policy["allow_" + prefix + ("_read" if read else "_trade")])


def available(plugin, event, read):
    def allowed(game):
        if read is None:
            return permitted(plugin, event, game, True) or permitted(plugin, event, game, False)
        return permitted(plugin, event, game, read)
    return [game for game in plugin.engine.games() if allowed(game)]


def resolve(plugin, event, read, instance_id=""):
    games = available(plugin, event, read)
    requested = str(instance_id)
    if requested:
        found = next((game for game in games if game["id"] == requested), None)
        if not found and requested.isascii() and requested.isdigit() and 1 <= int(requested) <= len(games):
            found = games[int(requested) - 1]
        if found:
            return found
        raise ValueError("实例不存在或管理员未允许当前会话使用此类工具")
    scope = str(event.unified_msg_origin) + "\x1f" + str(event.get_sender_id())
    plugin.engine.db.execute("CREATE TABLE IF NOT EXISTS shared_tool_selection(scope TEXT PRIMARY KEY,game TEXT NOT NULL)")
    row = plugin.engine.db.execute("SELECT game FROM shared_tool_selection WHERE scope=?", (scope,)).fetchone()
    if row:
        found = next((game for game in games if game["id"] == row[0]), None)
        if found:
            return found
    # Keep the usual private-chat selection if it is authorized for this operation.
    try:
        found = plugin.identity.selected(event)
        if any(game["id"] == found["id"] for game in games):
            return found
    except ValueError:
        pass
    if len(games) == 1:
        return games[0]
    if not games:
        raise ValueError("管理员未允许当前会话查看或操作交易实例")
    raise ValueError("有多个可用实例，请先查询实例列表，再指定 instance_id")


def selected_in_call(plugin):
    value = CURRENT.get()
    return plugin.engine.get(value) if value else None
