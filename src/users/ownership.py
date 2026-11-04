"""User ownership and administrator-issued bearer IDs; no password login."""

import re
import secrets
import time
import uuid
from . import policy

TOKEN_PATTERN = re.compile(r"krm_[0-9a-f]{20}")


def issue_id(db, uid):
    if not db.execute("SELECT 1 FROM sim_users WHERE id=?", (uid,)).fetchone():
        raise ValueError("用户不存在")
    while True:
        token = "krm_" + secrets.token_hex(10)
        if not db.execute(
            "SELECT 1 FROM sim_user_tokens WHERE token=?", (token,)
        ).fetchone():
            break
    db.execute(
        "INSERT INTO sim_user_tokens(user_id,token,generation,updated) VALUES(?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET token=excluded.token,generation=generation+1,updated=excluded.updated",
        (uid, token, time.time()),
    )
    return token


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sim_users(id TEXT PRIMARY KEY,nickname TEXT NOT NULL,ordinal INTEGER UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS sim_user_aliases(alias TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES sim_users(id));
    CREATE TABLE IF NOT EXISTS sim_user_tokens(user_id TEXT PRIMARY KEY REFERENCES sim_users(id),token TEXT UNIQUE NOT NULL,generation INTEGER NOT NULL,updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS sim_counters(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
    INSERT OR IGNORE INTO sim_counters VALUES('user',0);
    CREATE TABLE IF NOT EXISTS sim_deleted_instances(id TEXT PRIMARY KEY,deleted REAL NOT NULL);
    """)
    policy.initialize(db)
    for row in db.execute(
        "SELECT id FROM sim_users WHERE id NOT IN (SELECT user_id FROM sim_user_tokens)"
    ).fetchall():
        issue_id(db, row[0])


def normalize(binding):
    if not isinstance(binding, dict) or set(binding) - {"type", "values"}:
        raise ValueError("请选择QQ、UMO列表或管理员生成的随机用户ID")
    kind = binding.get("type")
    values = binding.get("values")
    if (
        kind not in ("qq", "umo", "random")
        or not isinstance(values, list)
        or len(values) > 20
    ):
        raise ValueError("用户绑定格式无效")
    if kind != "random" and not values:
        raise ValueError("绑定用户为必填")
    if kind in ("qq", "random") and len(values) > 1:
        raise ValueError("QQ号或随机ID只能填写一个")
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 300:
            raise ValueError("用户绑定格式无效")
        value = value.strip()
        if kind == "qq" and not re.fullmatch(r"[1-9][0-9]{4,11}", value):
            raise ValueError("请输入有效QQ号（5～12位数字）")
        if kind == "random" and not TOKEN_PATTERN.fullmatch(value):
            raise ValueError("随机用户ID格式无效，请复制后台生成的完整ID")
        if kind == "umo":
            parts = value.split(":")
            if (
                len(parts) != 3
                or not parts[0]
                or parts[1] != "FriendMessage"
                or not parts[2]
                or any(c.isspace() or ord(c) < 32 for c in value)
            ):
                raise ValueError(
                    "请输入完整私聊UMO，例如 default:FriendMessage:123456789"
                )
        if value not in result:
            result.append(value)
    return dict(type=kind, values=result)


def owner_for_token(db, token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token.strip()):
        raise ValueError("用户ID无效或已刷新，请使用管理员提供的新ID")
    row = db.execute(
        "SELECT user_id FROM sim_user_tokens WHERE token=?", (token.strip(),)
    ).fetchone()
    if not row:
        raise ValueError("用户ID无效或已刷新，请使用管理员提供的新ID")
    return row[0]


def resolve(db, binding, nickname=""):
    binding = normalize(binding)
    if (
        not isinstance(nickname, str)
        or len(nickname) > 40
        or any(ord(c) < 32 for c in nickname)
    ):
        raise ValueError("昵称须为40字以内的单行文字")
    aliases = []
    if binding["type"] == "random":
        owners = (
            {owner_for_token(db, binding["values"][0])} if binding["values"] else set()
        )
    else:
        aliases = [binding["type"] + ":" + v for v in binding["values"]]
        owners = {
            row[0]
            for alias in aliases
            for row in db.execute(
                "SELECT user_id FROM sim_user_aliases WHERE alias=?", (alias,)
            )
        }
    if len(owners) > 1:
        raise ValueError("这些UMO已属于不同用户，不能自动合并")
    if owners:
        uid = next(iter(owners))
        name = db.execute(
            "SELECT nickname FROM sim_users WHERE id=?", (uid,)
        ).fetchone()[0]
    else:
        db.execute("UPDATE sim_counters SET value=value+1 WHERE name='user'")
        ordinal = db.execute(
            "SELECT value FROM sim_counters WHERE name='user'"
        ).fetchone()[0]
        uid = uuid.uuid4().hex
        name = nickname.strip() or f"用户{ordinal}"
        db.execute("INSERT INTO sim_users VALUES(?,?,?)", (uid, name, ordinal))
        issue_id(db, uid)
    for alias in aliases:
        db.execute("INSERT OR IGNORE INTO sim_user_aliases VALUES(?,?)", (alias, uid))
    if binding["type"] == "random":
        binding = dict(type="random", values=[])
    return dict(owner_id=uid, owner_name=name, user_binding=binding)


def users(db):
    people = []
    for row in db.execute(
        "SELECT u.id,u.nickname,t.token FROM sim_users u JOIN sim_user_tokens t ON t.user_id=u.id ORDER BY ordinal"
    ):
        aliases = [
            dict(type=r[0].split(":", 1)[0], value=r[0].split(":", 1)[1])
            for r in db.execute(
                "SELECT alias FROM sim_user_aliases WHERE user_id=? ORDER BY alias",
                (row[0],),
            )
        ]
        instances = [
            dict(id=r[0], name=r[1], reference_umo=r[2] or "")
            for r in db.execute(
                "SELECT id,json_extract(data,'$.name'),json_extract(data,'$.reference_umo') FROM games WHERE json_extract(data,'$.owner_id')=?",
                (row[0],),
            )
        ]
        people.append(
            dict(
                id=row[0],
                name=row[1],
                public_id=row[2],
                bindings=aliases,
                instances=instances,
                policy=policy.for_user(db, row[0]),
                notifications=policy.notice_defaults(db, row[0]),
            )
        )
    return people
