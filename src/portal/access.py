"""One-time grants and scoped browser sessions."""

import hashlib
import secrets
import time


def digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def valid_token(token):
    return isinstance(token, str) and len(token) == 43 and token.isascii()


class PortalAccess:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS portal_grants(
          digest TEXT PRIMARY KEY,
          owner TEXT NOT NULL REFERENCES sim_users(id) ON DELETE CASCADE,
          game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          mode TEXT NOT NULL, expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS portal_grants_game ON portal_grants(game);
        CREATE TABLE IF NOT EXISTS portal_sessions(
          digest TEXT PRIMARY KEY,
          owner TEXT NOT NULL REFERENCES sim_users(id) ON DELETE CASCADE,
          game TEXT REFERENCES games(id) ON DELETE CASCADE,
          mode TEXT NOT NULL, expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS portal_sessions_owner ON portal_sessions(owner);
        CREATE INDEX IF NOT EXISTS portal_sessions_game ON portal_sessions(game);
        """)

    def own(self, owner, gid):
        game = self.engine.get(gid)
        if not owner or game.get("owner_id") != owner:
            raise ValueError("实例不存在或不属于当前用户")
        return game

    def cleanup(self, now):
        self.db.execute("DELETE FROM portal_grants WHERE expires<=?", (now,))
        self.db.execute("DELETE FROM portal_sessions WHERE expires<=?", (now,))

    def issue(self, owner, gid, mode):
        if mode not in {"read", "summary"}:
            raise ValueError("链接类型无效")
        self.own(owner, gid)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.engine.transaction():
            self.cleanup(now)
            self.db.execute("DELETE FROM portal_grants WHERE game=? AND mode=?", (gid, mode))
            self.db.execute(
                "INSERT INTO portal_grants VALUES(?,?,?,?,?)",
                (digest(token), owner, gid, mode, now + 300),
            )
        return token

    def session_token(self, owner, gid, mode, now, ttl):
        token = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO portal_sessions VALUES(?,?,?,?,?)",
            (digest(token), owner, gid, mode, now + ttl),
        )
        return token

    def exchange(self, token):
        if not valid_token(token):
            raise ValueError("链接已失效，请在私聊重新领取")
        now = time.time()
        with self.engine.transaction():
            self.cleanup(now)
            row = self.db.execute("SELECT * FROM portal_grants WHERE digest=?", (digest(token),)).fetchone()
            if row is None:
                raise ValueError("链接已失效，请在私聊重新领取")
            self.own(row["owner"], row["game"])
            self.db.execute("DELETE FROM portal_grants WHERE digest=?", (digest(token),))
            return self.session_token(row["owner"], row["game"], row["mode"], now, 3600)

    def session(self, token):
        if not valid_token(token):
            return None
        row = self.db.execute(
            "SELECT * FROM portal_sessions WHERE digest=? AND expires>?",
            (digest(token), time.time()),
        ).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        if valid_token(token):
            self.db.execute("DELETE FROM portal_sessions WHERE digest=?", (digest(token),))

    def revoke_links(self, gid):
        self.engine.get(gid)
        with self.engine.transaction():
            self.db.execute("DELETE FROM portal_grants WHERE game=?", (gid,))
            self.db.execute("DELETE FROM portal_sessions WHERE game=?", (gid,))

    def revoke_all(self):
        with self.engine.transaction():
            self.db.execute("DELETE FROM portal_grants")
            self.db.execute("DELETE FROM portal_sessions")
