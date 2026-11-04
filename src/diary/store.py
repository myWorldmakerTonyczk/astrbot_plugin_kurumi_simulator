"""Durable per-instance diary queue and timestamped, authorized chat archive."""

import json
import re
import time
from ..core.engine import dump


def redact(text):
    return re.sub(r"krm_[0-9a-fA-F]{20}", "[用户凭据已隐藏]", str(text))


class DiaryStore:
    def __init__(self, engine):
        self.engine, self.db = engine, engine.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS diaries(
          game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          day TEXT NOT NULL, zone TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
          status TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
          attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
          updated REAL NOT NULL, PRIMARY KEY(game,day));
        CREATE TABLE IF NOT EXISTS diary_chat(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          umo TEXT NOT NULL, message_id TEXT NOT NULL, role TEXT NOT NULL,
          content TEXT NOT NULL, created REAL NOT NULL,
          UNIQUE(game,umo,message_id,role));
        CREATE INDEX IF NOT EXISTS diary_chat_period ON diary_chat(game,created,seq);
        CREATE INDEX IF NOT EXISTS diary_queue ON diaries(status,retry_at,day);
        CREATE INDEX IF NOT EXISTS logs_period ON logs(game,created,seq);
        """)

    def recover(self):
        self.db.execute(
            "UPDATE diaries SET status='pending',retry_at=0 WHERE status='running'"
        )

    def capture(self, plugin, event, role, content, now=None):
        if not isinstance(content, str) or not content.strip():
            return
        try:
            umo, _, _ = plugin.identity.event_scope(event)
        except (ValueError, AttributeError):
            return
        if (
            getattr(getattr(event, "platform_meta", None), "name", "")
            == "kurumi_silent"
        ):
            return
        message_id = str(getattr(getattr(event, "message_obj", None), "message_id", ""))
        if not message_id:
            return  # Do not deduplicate unrelated events with an empty ID.
        for game in self.engine.games():
            if (
                game.get("reference_umo") or game.get("umo")
            ) != umo or not plugin.identity.can_reference(game.get("owner_id"), umo):
                continue
            self.db.execute(
                "INSERT OR IGNORE INTO diary_chat(game,umo,message_id,role,content,created) VALUES(?,?,?,?,?,?)",
                (
                    game["id"],
                    umo,
                    message_id,
                    role,
                    redact(content)[:12000],
                    time.time() if now is None else now,
                ),
            )

    def count_logs(self, gid, start, end):
        # Background summaries/settings are not trading activity.
        return self.db.execute(
            "SELECT count(*) FROM logs WHERE game=? AND created>=? AND created<? "
            "AND json_extract(data,'$.action') NOT IN ('analysis','bind','market_source','create')",
            (gid, start, end),
        ).fetchone()[0]

    def has_chat(self, gid, start, end):
        return bool(
            self.db.execute(
                "SELECT 1 FROM diary_chat WHERE game=? AND created>=? AND created<? LIMIT 1",
                (gid, start, end),
            ).fetchone()
        )

    def enqueue(self, gid, day, zone, start, end, now):
        self.engine.get(gid)
        self.db.execute(
            "INSERT OR IGNORE INTO diaries(game,day,zone,start,end,status,updated) VALUES(?,?,?,?,?,'pending',?)",
            (gid, day, zone, start, end, now),
        )
        self.db.execute(
            "UPDATE diaries SET status='pending',updated=? WHERE game=? AND day=? AND status='skipped'",
            (now, gid, day),
        )

    def get(self, gid, day):
        self.engine.get(gid)
        row = self.db.execute(
            "SELECT * FROM diaries WHERE game=? AND day=?", (gid, day)
        ).fetchone()
        if not row:
            raise ValueError("日记任务不存在")
        return dict(row)

    def list(self, gid, before="", limit=10):
        self.engine.get(gid)
        if (
            not isinstance(before, str)
            or type(limit) is not int
            or not 1 <= limit <= 30
        ):
            raise ValueError("日记分页参数无效")
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT day,zone,status,content,error,attempts,updated FROM diaries WHERE game=? AND day<? ORDER BY day DESC LIMIT ?",
                (gid, before or "9999-12-31", limit),
            )
        ]

    def finish(self, gid, day, content, now):
        self.engine.get(gid)  # Never recreate deleted instances.
        self.db.execute(
            "UPDATE diaries SET status='success',content=?,error='',updated=? WHERE game=? AND day=? AND status='running'",
            (redact(content), now, gid, day),
        )

    def records(self, plugin, job, kind, before=0, limit=30):
        gid, cutoff = job["game"], job["end"]
        game = self.engine.get(gid)
        if (
            type(before) is not int
            or before < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("查询条数须为1～50，游标须为非负整数")
        cursor = before or 2**63 - 1
        if kind == "logs":
            rows = [
                dict(id=row[0], **json.loads(row[1]))
                for row in self.db.execute(
                    "SELECT seq,data FROM logs WHERE game=? AND created<? AND seq<? "
                    "AND json_extract(data,'$.action') NOT IN ('analysis','bind','market_source','create') ORDER BY seq DESC LIMIT ?",
                    (gid, cutoff, cursor, limit),
                )
            ]
        elif kind == "chat":
            umo = game.get("reference_umo") or game.get("umo", "")
            if not plugin.identity.can_reference(game.get("owner_id"), umo):
                return dict(records=[], next_before=0, note="没有已授权的关联会话")
            rows = [
                dict(row)
                for row in self.db.execute(
                    "SELECT seq AS id,role,content,created FROM diary_chat WHERE game=? AND umo=? AND created<? AND seq<? ORDER BY seq DESC LIMIT ?",
                    (gid, umo, cutoff, cursor, limit),
                )
            ]
        else:
            raise ValueError("不支持的记录类型")
        return json.loads(
            redact(dump(dict(records=rows, next_before=rows[-1]["id"] if rows else 0)))
        )
