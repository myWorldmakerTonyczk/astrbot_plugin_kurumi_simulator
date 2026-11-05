"""Dashboard-only portal configuration and revocation."""

from astrbot.api.web import error_response, json_response, request

from ..core.engine import dump
from ..portal.server import settings


class PortalApiMixin:
    async def web_portal_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            if isinstance(body, dict) and set(body) == {"revoke_game"}:
                self.portal.access.revoke_links(body["revoke_game"])
            else:
                config = settings(body)
                await self.portal.configure(config)
                with self.engine.transaction():
                    saved = self.settings()
                    saved["portal"] = config
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(saved),))
            return json_response(dict(ok=True, portal=self.portal.public()))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
