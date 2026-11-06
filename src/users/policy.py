"""Administrator-owned user preferences and effective instance permissions."""

import json
from ..notifications.settings import validate as notification_settings

DEFAULTS = dict(
    allow_custom_interval=False,
    max_instances=0,
    interval=3600,
    allow_panel_notice=True,
    allow_tool_notice=True,
)


def initialize(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS sim_user_policy(user_id TEXT PRIMARY KEY REFERENCES sim_users(id),data TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS sim_user_notice_defaults(user_id TEXT PRIMARY KEY REFERENCES sim_users(id),data TEXT NOT NULL)"
    )


def notice_defaults(db, uid):
    row = db.execute(
        "SELECT data FROM sim_user_notice_defaults WHERE user_id=?", (uid,)
    ).fetchone()
    return notification_settings(json.loads(row[0]) if row else None)


def for_user(db, uid):
    row = db.execute(
        "SELECT data FROM sim_user_policy WHERE user_id=?", (uid,)
    ).fetchone()
    values = {**DEFAULTS, **(json.loads(row[0]) if row else {})}
    values["interval"] = max(600, int(values["interval"]))
    return values


def effective(engine, game):
    policy = for_user(engine.db, game.get("owner_id", ""))
    interval = policy["interval"]
    return dict(
        **policy,
        effective_interval=interval,
        notifications=notification_settings(game.get("notifications")),
    )


def validate(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError("用户权限设置字段无效")
    if any(
        type(values[key]) is not bool
        for key in DEFAULTS
        if key not in ("interval", "max_instances")
    ):
        raise ValueError("用户权限开关须为布尔值")
    if type(values["interval"]) is not int or not 600 <= values["interval"] <= 86400:
        raise ValueError("看盘间隔须在10分钟～24小时之间")
    if (
        type(values["max_instances"]) is not int
        or not 0 <= values["max_instances"] <= 1000
    ):
        raise ValueError("实例数量上限须为0～1000，0表示不限")
    return dict(values)


def update(engine, uid, nickname, values, notices):
    if (
        not isinstance(nickname, str)
        or not nickname.strip()
        or len(nickname) > 40
        or any(ord(c) < 32 for c in nickname)
    ):
        raise ValueError("用户名须为1～40字的单行文字")
    values = validate(values)
    notices = notification_settings(notices)
    with engine.transaction():
        apply(engine, uid, nickname.strip(), values, notices)
    return dict(ok=True)


def apply(engine, uid, nickname, values, notices):
    if not engine.db.execute(
        "SELECT 1 FROM sim_users WHERE id=?", (uid,)
    ).fetchone():
        raise ValueError("用户不存在")
    previous = for_user(engine.db, uid)
    previous_notices = notice_defaults(engine.db, uid)
    engine.db.execute(
        "UPDATE sim_users SET nickname=? WHERE id=?", (nickname.strip(), uid)
    )
    engine.db.execute(
        "INSERT OR REPLACE INTO sim_user_policy VALUES(?,?)",
        (uid, json.dumps(values)),
    )
    engine.db.execute(
        "INSERT OR REPLACE INTO sim_user_notice_defaults VALUES(?,?)",
        (uid, json.dumps(notices)),
    )
    for game in engine.games():
        if game.get("owner_id") != uid:
            continue
        game["owner_name"] = nickname.strip()
        if (
            not values["allow_custom_interval"]
            or previous["interval"] != values["interval"]
        ):
            game["interval"] = values["interval"]
        if notices != previous_notices:
            game["notifications"] = notices
        game["action_revision"] = game.get("action_revision", 0) + 1
        engine.save(game)
        engine.log(
            game,
            "human",
            "bind",
            "管理员修改用户名称、自动分析权限或主动汇报设置",
            {},
        )


def change_notices(plugin, gid, changes, source):
    if not isinstance(changes, dict):
        raise ValueError("通知设置须为对象")
    game = plugin.engine.get(gid)
    policy = for_user(plugin.engine.db, game.get("owner_id", ""))
    key = "allow_tool_notice" if source == "ai" else "allow_panel_notice"
    if not policy[key]:
        raise ValueError(
            "管理员未允许通过工具修改通知"
            if source == "ai"
            else "通知由管理员统一设置，请到用户与权限中修改"
        )
    notices = notification_settings(
        {**notification_settings(game.get("notifications")), **changes}
    )
    with plugin.engine.transaction():
        game = plugin.engine.get(gid)
        game["notifications"] = notices
        plugin.engine.save(game)
        plugin.engine.log(game, source, "bind", "调整本实例主动汇报与免打扰设置", {})
    return dict(ok=True, notifications=notices)


def sync_interval(engine, uid, interval):
    """Called within the binding transaction; both panels share this value."""
    values = for_user(engine.db, uid)
    values["interval"] = interval
    validate(values)
    engine.db.execute(
        "INSERT OR REPLACE INTO sim_user_policy VALUES(?,?)", (uid, json.dumps(values))
    )
    for game in engine.games():
        if game.get("owner_id") == uid:
            game["interval"] = interval
            engine.save(game)
