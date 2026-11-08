"""One persistent decision queue for manual, periodic and risk-driven tasks."""

import asyncio
import json
from astrbot.api import logger
import time
from ..core.engine import dump
from ..core.replay_records import decision_scope
from ..users.policy import effective
from ..diary.store import redact
from .decision_settings import settings
from ..core.availability import automatic_break, require_active, run_automatic


class DecisionService:
    def __init__(self, plugin, runner=None):
        self.plugin, self.db, self.runner = plugin, plugin.engine.db, runner
        self.lock = asyncio.Lock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS decision_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          trigger TEXT NOT NULL,events TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,
          updated REAL NOT NULL,error TEXT NOT NULL DEFAULT '',result TEXT NOT NULL DEFAULT '');
        CREATE UNIQUE INDEX IF NOT EXISTS decision_one_pending ON decision_jobs(game) WHERE state='pending';
        CREATE INDEX IF NOT EXISTS decision_queue ON decision_jobs(state,created);
        CREATE TABLE IF NOT EXISTS decision_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,
          game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS decision_rate ON decision_attempts(game,created);
        CREATE TABLE IF NOT EXISTS decision_cursor(game TEXT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,seq INTEGER NOT NULL);
        """)
        # Upgrading does not replay every old stop-loss. Saved cursors continue on restart.
        for game in plugin.engine.games():
            self.db.execute(
                "INSERT OR IGNORE INTO decision_cursor VALUES(?,?)",
                (game["id"], self.last_seq(game["id"])),
            )

    def config(self):
        return settings(self.plugin.settings().get("decision_limits"))

    def last_seq(self, gid):
        return self.db.execute(
            "SELECT COALESCE(MAX(seq),0) FROM logs WHERE game=?", (gid,)
        ).fetchone()[0]

    def recover(self):
        # A newer pending event may already exist: merge instead of violating the unique index.
        for row in self.db.execute(
            "SELECT * FROM decision_jobs WHERE state='running'"
        ).fetchall():
            other = self.db.execute(
                "SELECT id FROM decision_jobs WHERE game=? AND state='pending'",
                (row["game"],),
            ).fetchone()
            if other:
                self.enqueue(
                    row["game"],
                    row["trigger"],
                    json.loads(row["events"]),
                    row["created"],
                )
                self.db.execute(
                    "UPDATE decision_jobs SET state='interrupted' WHERE id=?",
                    (row["id"],),
                )
            else:
                self.db.execute(
                    "UPDATE decision_jobs SET state='pending' WHERE id=?", (row["id"],)
                )

    def next_allowed(self, gid, now=None):
        now = time.time() if now is None else now
        config = self.config()
        rows = [
            r[0]
            for r in self.db.execute(
                "SELECT created FROM decision_attempts WHERE game=? ORDER BY created DESC LIMIT ?",
                (gid, config["hourly_limit"]),
            )
        ]
        due = rows[0] + config["cooldown"] if rows else 0
        recent = [stamp for stamp in rows if stamp > now - 3600]
        if len(recent) >= config["hourly_limit"]:
            due = max(due, recent[-1] + 3600)
        return max(now, due)

    def active(self, gid):
        return self.db.execute(
            "SELECT * FROM decision_jobs WHERE game=? AND state IN ('pending','running') ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,id LIMIT 1",
            (gid,),
        ).fetchone()

    def enqueue(self, gid, trigger, events=None, now=None):
        require_active(self.plugin.engine.get(gid))
        now = time.time() if now is None else now
        events = events or []
        row = self.db.execute(
            "SELECT * FROM decision_jobs WHERE game=? AND state='pending'", (gid,)
        ).fetchone()
        if row:
            prior = json.loads(row["events"])
            combined = {e["id"]: e for e in [*prior, *events]}
            merged = list(sorted(combined.values(), key=lambda e: e["id"]))[-50:]
            self.db.execute(
                "UPDATE decision_jobs SET events=?,trigger=?,updated=? WHERE id=?",
                (
                    dump(merged),
                    "风险事件复盘" if merged else row["trigger"],
                    now,
                    row["id"],
                ),
            )
            return row["id"]
        cursor = self.db.execute(
            "INSERT INTO decision_jobs(game,trigger,events,state,created,updated) VALUES(?,?,?,'pending',?,?)",
            (gid, trigger, dump(events[-50:]), now, now),
        )
        return cursor.lastrowid

    def request_manual(self, gid, now=None):
        game = self.plugin.engine.get(gid)
        require_active(game)
        active = self.active(gid)
        if active and active["state"] == "pending" and active["trigger"] == "定时看盘":
            self.db.execute(
                "UPDATE decision_jobs SET trigger='手动看盘' WHERE id=?",
                (active["id"],),
            )
        if not active:
            from .llm import ensure_available

            ensure_available(self.plugin, game)
            if game["status"] == "running":
                for pair in game["pairs"]:
                    self.plugin.engine.quote(pair)
            self.enqueue(gid, "手动看盘", now=now)
        return self.state(gid, now)

    def scan(self, now=None):
        now = time.time() if now is None else now
        config = self.config()
        for game in self.plugin.engine.games():
            row = self.db.execute(
                "SELECT seq FROM decision_cursor WHERE game=?", (game["id"],)
            ).fetchone()
            after = row[0] if row else 0
            rows = self.db.execute(
                "SELECT seq,data FROM logs WHERE game=? AND seq>? ORDER BY seq LIMIT 200",
                (game["id"], after),
            ).fetchall()
            events = []
            for seq, raw in rows:
                entry = json.loads(raw)
                if entry.get("status") == "rejected":
                    continue
                action, detail, reason = (
                    entry["action"],
                    entry.get("detail", {}),
                    entry.get("reason", ""),
                )
                kind = action if action in ("margin_call", "end") else ""
                if action == "close" and entry.get("source") == "system":
                    if detail.get("kind") == "liquidation" or "强平" in reason:
                        kind = "liquidation"
                    elif reason == "触发止损":
                        kind = "stop_loss"
                    elif reason == "触发止盈":
                        kind = "take_profit"
                if kind and config[kind]:
                    events.append(
                        json.loads(
                            redact(
                                dump(
                                    dict(
                                        id=seq,
                                        kind=kind,
                                        created=entry["created"],
                                        reason=reason,
                                        detail=detail,
                                    )
                                )
                            )
                        )
                    )
            with self.plugin.engine.transaction():
                if events and game["status"] != "paused" and not automatic_break(now, config):
                    self.enqueue(game["id"], "风险事件复盘", events, now)
                self.db.execute(
                    "INSERT OR REPLACE INTO decision_cursor VALUES(?,?)",
                    (game["id"], rows[-1][0] if rows else after),
                )
                if (
                    game["auto"]
                    and not automatic_break(now, config)
                    and game["status"] == "running"
                    and now - game["last_decision"]
                    >= effective(self.plugin.engine, game)["effective_interval"]
                    and not self.active(game["id"])
                ):
                    self.enqueue(game["id"], "定时看盘", now=now)

    def state(self, gid, now=None):
        self.plugin.engine.get(gid)
        now = time.time() if now is None else now
        row = self.active(gid)
        latest = self.db.execute(
            "SELECT * FROM decision_jobs WHERE game=? AND state IN ('success','failed') ORDER BY id DESC LIMIT 1",
            (gid,),
        ).fetchone()
        return dict(
            state=row["state"] if row else latest["state"] if latest else "idle",
            job_id=row["id"] if row else latest["id"] if latest else None,
            trigger=row["trigger"] if row else latest["trigger"] if latest else "",
            next_allowed=self.next_allowed(gid, now),
            last_summary=(
                json.loads(latest["result"]).get("summary", "")
                if latest and latest["result"]
                else ""
            ),
            error=latest["error"] if latest else "",
            queued_events=len(json.loads(row["events"])) if row else 0,
        )

    async def process_one(self, now=None):
        if self.lock.locked():
            return False
        async with self.lock:
            now = time.time() if now is None else now
            selected = None
            for row in self.db.execute(
                "SELECT * FROM decision_jobs WHERE state='pending' ORDER BY created,id"
            ).fetchall():
                game = self.plugin.engine.get(row["game"])
                if game["status"] == "paused" or (row["trigger"] != "手动看盘" and automatic_break(now, self.config())):
                    continue
                if (
                    row["trigger"] == "定时看盘"
                    and not self.plugin.engine.get(row["game"])["auto"]
                ):
                    self.db.execute(
                        "UPDATE decision_jobs SET state='cancelled',updated=? WHERE id=?",
                        (now, row["id"]),
                    )
                    continue
                if self.next_allowed(row["game"], now) <= now:
                    selected = dict(row)
                    break
            if not selected:
                return False
            gid = selected["game"]
            with self.plugin.engine.transaction():
                self.db.execute(
                    "UPDATE decision_jobs SET state='running',updated=? WHERE id=?",
                    (now, selected["id"]),
                )
                self.db.execute(
                    "INSERT INTO decision_attempts(game,created) VALUES(?,?)",
                    (gid, now),
                )
                game = self.plugin.engine.get(gid)
                game["last_decision"] = now
                self.plugin.engine.save(game)
            try:
                if self.runner is None:
                    from .runner import decide
                else:
                    decide = self.runner
                scope = decision_scope.set((gid, selected["id"]))
                try:
                    result = await run_automatic(self.plugin, gid, decide(
                        self.plugin, gid, selected["trigger"], events=json.loads(selected["events"])
                    ))
                finally:
                    decision_scope.reset(scope)
                self.db.execute(
                    "UPDATE decision_jobs SET state='success',result=?,error='',updated=? WHERE id=?",
                    (dump(result), time.time(), selected["id"]),
                )
                game = self.plugin.engine.get(gid)
                game["last_analysis_error"] = ""
                self.plugin.engine.save(game)
            except asyncio.CancelledError:
                # Recovery merges this job on the next plugin start.
                raise
            except Exception as exc:
                text = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "模型请求失败，请检查接口、密钥与工具调用支持"
                )
                self.db.execute(
                    "UPDATE decision_jobs SET state='failed',error=?,updated=? WHERE id=?",
                    (text[:500], time.time(), selected["id"]),
                )
                try:
                    game = self.plugin.engine.get(gid)
                    game["last_analysis_error"] = text
                    self.plugin.engine.save(game)
                except ValueError:
                    pass
                logger.warning("[Kurumi] 看盘任务失败：%s", text)
            return True

    async def loop(self):
        self.recover()
        while True:
            try:
                self.scan()
                if await self.process_one():
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[Kurumi] 看盘队列暂不可用，将自动重试")
            await asyncio.sleep(5)
