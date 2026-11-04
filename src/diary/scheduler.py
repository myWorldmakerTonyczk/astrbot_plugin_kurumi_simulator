"""One durable, serial diary queue for the whole plugin, independent of quotes."""

import asyncio
import json
from astrbot.api import logger
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .settings import settings, bounds, due_before
from .store import DiaryStore


class DiaryService:
    def __init__(self, plugin, writer=None):
        self.plugin = plugin
        self.store = DiaryStore(plugin.engine)
        self.lock = asyncio.Lock()
        self.scan_key = None
        self.writer = writer

    def config(self):
        return settings(self.plugin.settings().get("diary"))

    def scan(self, now=None):
        now = time.time() if now is None else now
        config = self.config()
        if not config["enabled"]:
            return
        until = due_before(now, config)
        key = (str(until), json.dumps(config, sort_keys=True))
        if key == self.scan_key:
            return
        for game in self.plugin.engine.games():
            day = datetime.fromtimestamp(
                game["created"], ZoneInfo(config["timezone"])
            ).date()
            while day <= until:
                start, end = bounds(day.isoformat(), config["timezone"])
                count = self.store.count_logs(game["id"], start, end)
                if count > config["min_logs"] or (
                    config["chat_only"]
                    and count == 0
                    and self.store.has_chat(game["id"], start, end)
                ):
                    self.store.enqueue(
                        game["id"], day.isoformat(), config["timezone"], start, end, now
                    )
                day += timedelta(days=1)
        self.scan_key = key

    async def process_one(self, now=None):
        if self.lock.locked():
            return False
        async with self.lock:
            config = self.config()
            if not config["enabled"]:
                return False
            now = time.time() if now is None else now
            row = self.store.db.execute(
                "SELECT * FROM diaries WHERE status IN ('pending','failed') AND retry_at<=? ORDER BY day,updated,game LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                return False
            job = dict(row)
            count = self.store.count_logs(job["game"], job["start"], job["end"])
            if not (
                count > config["min_logs"]
                or (
                    config["chat_only"]
                    and count == 0
                    and self.store.has_chat(job["game"], job["start"], job["end"])
                )
            ):
                self.store.db.execute(
                    "UPDATE diaries SET status='skipped',updated=? WHERE game=? AND day=?",
                    (now, job["game"], job["day"]),
                )
                return True
            self.store.db.execute(
                "UPDATE diaries SET status='running',attempts=attempts+1,updated=? WHERE game=? AND day=?",
                (now, job["game"], job["day"]),
            )
            try:
                if self.writer is None:
                    from .writer import write
                else:
                    write = self.writer
                content = await write(self.plugin, job, config)
                self.store.finish(job["game"], job["day"], content, time.time())
            except asyncio.CancelledError:
                self.store.db.execute(
                    "UPDATE diaries SET status='pending',retry_at=0 WHERE game=? AND day=?",
                    (job["game"], job["day"]),
                )
                raise
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "日记生成失败，请检查模型连接与工具调用支持"
                )
                retry = now + min(21600, 300 * 2 ** min(job["attempts"], 6))
                self.store.db.execute(
                    "UPDATE diaries SET status='failed',error=?,retry_at=?,updated=? WHERE game=? AND day=?",
                    (message[:500], retry, now, job["game"], job["day"]),
                )
                logger.warning("[Kurumi] 日记任务失败：%s", message)
            return True

    async def loop(self):
        self.store.recover()
        while True:
            try:
                self.scan()
                if await self.process_one():
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[Kurumi] 日记队列暂不可用，将自动重试")
            await asyncio.sleep(30)
