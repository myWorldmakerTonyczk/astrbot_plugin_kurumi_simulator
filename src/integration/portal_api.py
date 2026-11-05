"""Dashboard-only portal configuration and revocation."""

from astrbot.api.web import error_response, json_response, request

from ..core.engine import dump
from ..portal.server import settings


class PortalApiMixin:
    def portal_instance(self, gid):
        game = self.engine.get(gid)
        return dict(
            owned=bool(game.get("owner_id")),
            trade=self.portal.accounts.trade_allowed(game),
            username=self.portal.accounts.username(game.get("owner_id")),
        )

    async def web_portal_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            if isinstance(body, dict) and set(body) == {"revoke_game"}:
                self.portal.access.revoke_links(body["revoke_game"])
            elif isinstance(body, dict) and set(body) == {"trade_game", "allowed"}:
                self.portal.accounts.allow_trade(body["trade_game"], body["allowed"])
            elif isinstance(body, dict) and set(body) == {"reset_account"}:
                game = self.engine.get(body["reset_account"])
                if not game.get("owner_id"):
                    raise ValueError("实例未绑定用户")
                self.portal.accounts.reset(game["owner_id"])
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
