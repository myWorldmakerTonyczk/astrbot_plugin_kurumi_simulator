"""Authenticated model settings; secrets are only accepted, never returned."""

from astrbot.api.web import request, json_response, error_response
from ..agent.llm import settings, public
from ..core.engine import dump
from ..agent.decision_settings import settings as decision_settings


class SettingsApiMixin:
    async def web_llm_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            config = settings(self.settings().get("llm"), body)
            if (
                config["mode"] == "platform"
                and config["provider_id"]
                and not self.context.get_provider_by_id(config["provider_id"])
            ):
                raise ValueError("所选平台模型不存在")
            with self.engine.transaction():
                saved = self.settings()
                saved["llm"] = config
                self.engine.db.execute(
                    "INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(saved),)
                )
                for game in self.engine.games():
                    game["action_revision"] = game.get("action_revision", 0) + 1
                    self.engine.save(game)
            return json_response(dict(ok=True, settings=public(config)))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    async def web_decision_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            if not isinstance(body, dict):
                raise ValueError("看盘设置须为对象")
            config = decision_settings(body)
            with self.engine.transaction():
                saved = self.settings()
                saved["decision_limits"] = config
                self.engine.db.execute(
                    "INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(saved),)
                )
            return json_response(dict(ok=True, settings=config))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
