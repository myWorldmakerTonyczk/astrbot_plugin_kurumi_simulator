"""Dashboard-admin diary API, separate from quote settings and trading writes."""

from astrbot.api.web import request, json_response, error_response
from ..core.engine import dump
from ..diary.settings import settings


class DiaryApiMixin:
    async def web_diary_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            if not isinstance(body, dict):
                raise ValueError("日记设置须为对象")
            config = settings(body)
            with self.engine.transaction():
                saved = self.settings()
                saved["diary"] = config
                self.engine.db.execute(
                    "INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(saved),)
                )
            self.diary.scan_key = None
            return json_response(dict(ok=True, settings=config))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    async def web_diaries(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            gid = request.query.get("game", "")
            rows = self.diary.store.list(
                gid,
                request.query.get("before", ""),
                int(request.query.get("limit", "10")),
            )
            return json_response(
                dict(entries=rows, next_before=rows[-1]["day"] if rows else "")
            )
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
