"""Password credentials and per-instance trade grants for the user portal."""

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from collections import deque

ACCOUNT_TTL = 8 * 3600
USERNAME = re.compile(r"krm-user-[0-9a-f]{12}")


def password_hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


class PortalAccounts:
    def __init__(self, access):
        self.access = access
        self.db = access.db
        self.hash_slots = asyncio.Semaphore(2)
        self.attempts = deque()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS portal_accounts(
          owner TEXT PRIMARY KEY REFERENCES sim_users(id) ON DELETE CASCADE,
          username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, verifier BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS portal_trade(
          game TEXT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
          owner TEXT NOT NULL REFERENCES sim_users(id) ON DELETE CASCADE);
        """)

    def username(self, owner):
        row = self.db.execute("SELECT username FROM portal_accounts WHERE owner=?", (owner,)).fetchone()
        return row[0] if row else ""

    def has_games(self, owner):
        return bool(self.db.execute(
            "SELECT 1 FROM games WHERE json_extract(data,'$.owner_id')=? LIMIT 1", (owner,)
        ).fetchone())

    async def issue(self, owner):
        if not self.has_games(owner):
            raise ValueError("当前用户还没有交易实例")
        existing = self.username(owner)
        if existing:
            return existing, ""
        if self.hash_slots.locked():
            raise ValueError("账号服务繁忙，请稍后再试")
        username = "krm-user-" + secrets.token_hex(6)
        password = secrets.token_urlsafe(18)
        salt = secrets.token_bytes(16)
        async with self.hash_slots:
            verifier = await asyncio.to_thread(password_hash, password, salt)
        if not self.has_games(owner):
            raise ValueError("当前用户的实例访问已撤销")
        inserted = self.db.execute(
            "INSERT INTO portal_accounts VALUES(?,?,?,?) ON CONFLICT(owner) DO NOTHING",
            (owner, username, salt, verifier),
        ).rowcount
        return (username, password) if inserted else (self.username(owner), "")

    def rate_limit(self, username):
        now = time.monotonic()
        while self.attempts and now - self.attempts[0][0] >= 60:
            self.attempts.popleft()
        if len(self.attempts) >= 30 or sum(name == username for _, name in self.attempts) >= 5:
            return False
        self.attempts.append((now, username))
        return True

    async def login(self, username, password):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            return None
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return None
        row = self.db.execute("SELECT * FROM portal_accounts WHERE username=?", (username,)).fetchone()
        salt = row["salt"] if row else bytes(16)
        async with self.hash_slots:
            verifier = await asyncio.to_thread(password_hash, password, salt)
        if not row or not hmac.compare_digest(verifier, row["verifier"]):
            return None
        # A reset or deletion during hashing invalidates the in-flight login.
        if self.username(row["owner"]) != username or not self.has_games(row["owner"]):
            return None
        now = time.time()
        with self.access.engine.transaction():
            self.access.cleanup(now)
            return self.access.session_token(row["owner"], None, "account", now, ACCOUNT_TTL)

    def reset(self, owner):
        with self.access.engine.transaction():
            self.db.execute("DELETE FROM portal_accounts WHERE owner=?", (owner,))
            self.db.execute("DELETE FROM portal_sessions WHERE owner=? AND mode='account'", (owner,))

    def trade_allowed(self, game):
        return bool(self.db.execute(
            "SELECT 1 FROM portal_trade WHERE game=? AND owner=?", (game["id"], game.get("owner_id"))
        ).fetchone())

    def allow_trade(self, gid, allowed):
        if type(allowed) is not bool:
            raise ValueError("交易权限须为布尔值")
        game = self.access.engine.get(gid)
        if not game.get("owner_id"):
            raise ValueError("请先绑定实例用户")
        with self.access.engine.transaction():
            if allowed:
                self.db.execute("INSERT OR REPLACE INTO portal_trade VALUES(?,?)", (gid, game["owner_id"]))
            else:
                self.db.execute("DELETE FROM portal_trade WHERE game=?", (gid,))
