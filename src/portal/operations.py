"""Account-only projections and the explicitly permitted simulation actions."""

import re

from aiohttp import web

from ..core.trading import lock_for
from ..diary.store import redact

ACTIONS = {
    "open": {"pair", "side", "units", "margin", "leverage", "sl", "tp"},
    "close": {"position"},
    "protect": {"position", "sl", "tp"},
}
POSITION_FIELDS = ("id", "pair", "side", "units", "margin", "entry", "current", "pnl", "sl", "tp", "leverage")


class Operations:
    def account_identity(self, request):
        session = self.identity(request)
        if session["mode"] != "account":
            raise web.HTTPForbidden()
        return session

    def describe_game(self, game, mode):
        return dict(
            id=game["id"],
            name="虚拟交易复盘" if mode == "summary" else redact(game["name"]),
            pairs=game["pairs"],
            trade=mode == "account" and self.accounts.trade_allowed(game),
        )

    async def account_state(self, request):
        session = self.account_identity(request)
        game = self.game(request, session)
        try:
            valuation = self.plugin.engine.valuation(game)
            positions = valuation["positions"]
            market_error = ""
        except ValueError:
            valuation = None
            positions = game["positions"]
            market_error = "行情暂不可用，请等待有效报价"
        quotes = {}
        for pair in game["pairs"]:
            try:
                quote = self.plugin.engine.quote(pair)
                quotes[pair] = {key: str(quote[key]) for key in ("bid", "ask")}
            except ValueError:
                continue
        return web.json_response(dict(
            game=self.describe_game(game, "account"),
            status=game["status"], leverage=game["leverage"], market_error=market_error,
            valuation={k: valuation[k] for k in ("equity", "free", "floating")} if valuation else None,
            quotes=quotes,
            positions=[{k: row[k] for k in POSITION_FIELDS if k in row} for row in positions],
        ))

    async def action(self, request):
        session = self.account_identity(request)
        body = await self.payload(request)
        action, params, key = body.get("action"), body.get("params"), body.get("request_id")
        if not isinstance(action, str) or action not in ACTIONS:
            raise web.HTTPForbidden()
        if not isinstance(params, dict) or set(params) - (ACTIONS[action] | {"reason"}):
            raise ValueError("交易参数无效")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9-]{16,64}", key):
            raise ValueError("交易请求编号无效")
        reason = params.get("reason")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("请填写 1～500 字的操作理由")
        if any(not isinstance(v, str) or len(v) > 500 for v in params.values()):
            raise ValueError("交易参数无效")
        game = self.game(request, session)
        if not self.accounts.trade_allowed(game):
            raise web.HTTPForbidden()
        lock = lock_for(self.plugin, game["id"])
        if lock.locked():
            raise ValueError("AI 正在看盘，请稍后再试")
        async with lock:
            if self.account_identity(request) != session:
                raise web.HTTPUnauthorized()
            game = self.game(request, session)
            if not self.accounts.trade_allowed(game):
                raise web.HTTPForbidden()
            if game["status"] != "running":
                raise ValueError("本局当前不可交易")
            result = self.plugin.engine.action(
                game["id"], action, dict(params, reason=redact(reason.strip())),
                "human", f"portal:{session['owner']}:{key}",
            )
        return web.json_response(dict(result, request_id=key))
