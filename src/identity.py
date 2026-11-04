"""Trusted message identity and per-user/per-session instance selection."""

from .ownership import owner_for_token

QQ_PLATFORMS = {"aiocqhttp", "qq_official", "qq", "onebot", "onebot_v11", "napcat"}


class Identity:
    def __init__(self, engine):
        self.engine = engine
        engine.db.executescript("""
        CREATE TABLE IF NOT EXISTS sim_selections(scope TEXT,user_id TEXT,instance_id TEXT,PRIMARY KEY(scope,user_id));
        CREATE TABLE IF NOT EXISTS sim_reference_grants(user_id TEXT,umo TEXT,PRIMARY KEY(user_id,umo));
        """)

    def event_scope(self, event):
        umo = str(event.unified_msg_origin)
        parts = umo.split(":")
        if len(parts) != 3 or parts[1] != "FriendMessage":
            raise ValueError("交易工具目前仅在私聊中使用")
        sender = str(event.get_sender_id())
        if not sender:
            raise ValueError("无法识别消息发送者")
        return umo, sender, umo + "\x1f" + sender

    def principal(self, event, user_id=""):
        umo, sender, scope = self.event_scope(event)
        if user_id:
            uid = owner_for_token(self.engine.db, user_id)
        else:
            row = self.engine.db.execute(
                "SELECT user_id FROM sim_user_aliases WHERE alias=?", ("umo:" + umo,)
            ).fetchone()
            if not row:
                platform = getattr(
                    getattr(event, "platform_meta", None), "name", ""
                ).lower()
                if platform in QQ_PLATFORMS:
                    row = self.engine.db.execute(
                        "SELECT user_id FROM sim_user_aliases WHERE alias=?",
                        ("qq:" + sender,),
                    ).fetchone()
            if not row:
                raise ValueError(
                    "当前会话未绑定用户；随机ID方式须在每次工具调用的user_id参数中携带完整ID"
                )
            uid = row[0]
        return uid, umo, sender, scope

    def instances(self, event, user_id=""):
        uid, *_ = self.principal(event, user_id)
        return [g for g in self.engine.games() if g.get("owner_id") == uid]

    def select(self, event, instance_id, user_id=""):
        uid, umo, sender, scope = self.principal(event, user_id)
        games = [g for g in self.engine.games() if g.get("owner_id") == uid]
        if str(instance_id).isdigit() and 1 <= int(instance_id) <= len(games):
            game = games[int(instance_id) - 1]
        else:
            game = next((g for g in games if g["id"] == instance_id), None)
        if not game:
            raise ValueError("实例不存在或不属于当前用户")
        with self.engine.transaction():
            self.engine.db.execute(
                "INSERT OR REPLACE INTO sim_selections VALUES(?,?,?)",
                (scope, uid, game["id"]),
            )
            self.engine.db.execute(
                "INSERT OR IGNORE INTO sim_reference_grants VALUES(?,?)", (uid, umo)
            )
            if not game.get("reference_umo"):
                game["reference_umo"] = umo
                self.engine.save(game)
        return game

    def selected(self, event, user_id=""):
        uid, umo, sender, scope = self.principal(event, user_id)
        row = self.engine.db.execute(
            "SELECT instance_id FROM sim_selections WHERE scope=? AND user_id=?",
            (scope, uid),
        ).fetchone()
        if row:
            try:
                game = self.engine.get(row[0])
                if game.get("owner_id") == uid:
                    return game
            except ValueError:
                pass
        games = [g for g in self.engine.games() if g.get("owner_id") == uid]
        if len(games) == 1:
            return self.select(event, games[0]["id"], user_id)
        if not games:
            raise ValueError("当前用户还没有交易实例，请联系管理员创建")
        raise ValueError(
            "当前用户有多个实例，请先调用kurumi_my_instances，再调用kurumi_select_instance选择"
        )

    def can_reference(self, uid, umo):
        if not uid or not umo:
            return False
        row = self.engine.db.execute(
            "SELECT 1 FROM sim_reference_grants WHERE user_id=? AND umo=?", (uid, umo)
        ).fetchone()
        alias = self.engine.db.execute(
            "SELECT 1 FROM sim_user_aliases WHERE user_id=? AND alias=?",
            (uid, "umo:" + umo),
        ).fetchone()
        return bool(row or alias)
