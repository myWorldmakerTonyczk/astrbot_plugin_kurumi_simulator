"""Persistent proactive outbox; every send, including emergencies, obeys quiet hours."""

import asyncio
import json
from astrbot.api import logger
import time
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
from ..diary.store import redact
from .settings import config, quiet, delivery_time


class NotificationService:
    def __init__(self, plugin):
        self.plugin, self.db = plugin, plugin.engine.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS notice_cursor(game TEXT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS notice_outbox(
          game TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,key TEXT NOT NULL,
          kind TEXT NOT NULL,body TEXT NOT NULL,due REAL NOT NULL,state TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',PRIMARY KEY(game,key));
        """)
        # Existing historical events are not replayed on first installation.
        for game in plugin.engine.games():
            self.db.execute(
                "INSERT OR IGNORE INTO notice_cursor VALUES(?,?)",
                (game["id"], self.last_seq(game["id"])),
            )

    def last_seq(self, gid):
        return self.db.execute(
            "SELECT COALESCE(MAX(seq),0) FROM logs WHERE game=?", (gid,)
        ).fetchone()[0]

    def enabled(self, preferences, kind):
        if kind == "diary":
            diary = self.plugin.diary.config()
            return preferences["enabled"] and diary["enabled"] and diary["send_to_owner"]
        return preferences["enabled"] and preferences.get(kind, False)

    def queue(self, game, key, kind, body, now):
        preferences = config(game)
        if not self.enabled(preferences, kind):
            return
        due = delivery_time(now, preferences, kind)
        self.db.execute(
            """INSERT INTO notice_outbox(game,key,kind,body,due,state) VALUES(?,?,?,?,?,'pending')
          ON CONFLICT(game,key) DO UPDATE SET body=excluded.body,
            due=CASE WHEN notice_outbox.state IN ('pending','failed') THEN notice_outbox.due ELSE excluded.due END,
            state='pending',error=''
          WHERE excluded.kind != 'diary' OR notice_outbox.state IN ('pending','failed')""",
            (game["id"], key, kind, redact(body)[:4000], due),
        )

    def scan(self, now=None):
        now = time.time() if now is None else now
        for game in self.plugin.engine.games():
            row = self.db.execute(
                "SELECT seq FROM notice_cursor WHERE game=?", (game["id"],)
            ).fetchone()
            after = row[0] if row else 0
            rows = self.db.execute(
                "SELECT seq,data FROM logs WHERE game=? AND seq>? ORDER BY seq LIMIT 200",
                (game["id"], after),
            ).fetchall()
            with self.plugin.engine.transaction():
                for seq, raw in rows:
                    event = json.loads(raw)
                    detail = event.get("detail", {})
                    action = event["action"]
                    kind = body = ""
                    if event.get("status") == "rejected":
                        continue
                    if action == "analysis" and event.get("reason") in ("定时看盘", "风险事件复盘"):
                        kind = "analysis"
                        when = datetime.fromtimestamp(
                            event["created"], ZoneInfo(config(game)["timezone"])
                        ).strftime("%m-%d %H:%M")
                        body = f"看盘汇报（{when}）\n{detail.get('summary', '本轮看盘已完成。')}"
                    elif action == "margin_call":
                        kind, body = (
                            "margin_call",
                            f"保证金不足，当前水平 {detail.get('level', '?')}%。可以追加虚拟资金或减少持仓；低于50%会模拟强平。",
                        )
                    elif action == "close" and (
                        detail.get("kind") == "liquidation"
                        or "强平" in event.get("reason", "")
                    ):
                        kind, body = (
                            "liquidation",
                            f"模拟强平提醒：{detail.get('position', {}).get('pair', '')} 的一笔持仓已被强平。{event.get('reason', '')}",
                        )
                    elif action == "deposit":
                        kind, body = (
                            "deposit",
                            f"收到追加的虚拟资金 ${detail.get('amount', '?')}，这笔追加不计入盈利。",
                        )
                    elif action == "end":
                        kind = "liquidation" if detail.get("bankrupt") else "end"
                        body = (
                            "爆仓，本局虚拟交易已结束。"
                            if detail.get("bankrupt")
                            else f"本局虚拟交易已结束：{detail.get('outcome', '')}"
                        )
                    if kind:
                        self.queue(
                            game,
                            "analysis" if kind == "analysis" else str(seq),
                            kind,
                            f"【{game['name']}】\n{body}",
                            now,
                        )
                self.db.execute(
                    "INSERT OR REPLACE INTO notice_cursor VALUES(?,?)",
                    (game["id"], rows[-1][0] if rows else after),
                )

    async def flush(self, now=None):
        frozen_clock = now is not None
        now = time.time() if now is None else now
        rows = self.db.execute(
            "SELECT * FROM notice_outbox WHERE state IN ('pending','failed') AND due<=? ORDER BY CASE kind WHEN 'analysis' THEN 1 ELSE 0 END,due LIMIT 20",
            (now,),
        ).fetchall()
        for row in rows:
            if not frozen_clock:
                now = time.time()
            gid, key = row["game"], row["key"]
            try:
                game = self.plugin.engine.get(gid)
            except ValueError:
                continue
            if game["status"] == "paused":
                continue
            preferences = config(game)
            if not self.enabled(preferences, row["kind"]):
                self.db.execute(
                    "UPDATE notice_outbox SET state='cancelled' WHERE game=? AND key=?",
                    (gid, key),
                )
                continue
            # Re-read current preferences right before sending; queued urgent items have no bypass.
            clock = datetime.fromtimestamp(
                now, ZoneInfo(preferences["timezone"])
            ).strftime("%H:%M")
            start, end = preferences["window_start"], preferences["window_end"]
            inside = (
                start <= clock < end if start < end else clock >= start or clock < end
            )
            if quiet(now, preferences) or (
                row["kind"] == "analysis" and preferences["use_window"] and not inside
            ):
                self.db.execute(
                    "UPDATE notice_outbox SET due=? WHERE game=? AND key=?",
                    (delivery_time(now, preferences, row["kind"]), gid, key),
                )
                continue
            umo = game.get("reference_umo") or game.get("umo", "")
            if (row["kind"] == "diary" and ":FriendMessage:" not in umo) or not self.plugin.identity.can_reference(game.get("owner_id"), umo):
                self.db.execute(
                    "UPDATE notice_outbox SET due=?,state='failed',error=? WHERE game=? AND key=?",
                    (now + 300, "请先通过交易工具关联已验证的私聊会话", gid, key),
                )
                continue
            try:
                await asyncio.wait_for(self.send(umo, row["body"]), timeout=30)
                self.db.execute(
                    "UPDATE notice_outbox SET state='sent',error='' WHERE game=? AND key=?",
                    (gid, key),
                )
                # Preserve the actually delivered text for future diaries without touching framework history.
                event = SimpleNamespace(
                    unified_msg_origin=umo,
                    get_sender_id=lambda: umo.split(":")[-1],
                    platform_meta=SimpleNamespace(name="kurumi_notice"),
                    message_obj=SimpleNamespace(
                        message_id=f"notice:{key}:{row['due']}"
                    ),
                )
                try:
                    if row["kind"] != "diary" and self.plugin.diary.config()["enabled"]:
                        self.plugin.diary.store.capture(
                            self.plugin, event, "assistant", row["body"], now
                        )
                except Exception:
                    logger.warning("[Kurumi] 主动消息已发送，日记归档暂失败")
            except asyncio.CancelledError:
                raise
            except Exception:
                self.db.execute(
                    "UPDATE notice_outbox SET state='failed',attempts=attempts+1,error=?,due=? WHERE game=? AND key=?",
                    (
                        "主动消息发送失败，将自动重试",
                        now + min(3600, 60 * 2 ** min(row["attempts"], 6)),
                        gid,
                        key,
                    ),
                )

    async def send(self, umo, body):
        from astrbot.api.event import MessageChain

        result = await self.plugin.context.send_message(
            umo, MessageChain().message(body)
        )
        if result is False:
            raise ValueError("平台未确认发送")

    async def loop(self):
        while True:
            try:
                self.scan()
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[Kurumi] 主动通知队列暂不可用，将自动重试")
            await asyncio.sleep(10)
