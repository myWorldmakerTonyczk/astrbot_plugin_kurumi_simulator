"""Separate, opt-in web listener with its own browser identity boundary."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from ..core.replay import review
from ..diary.store import redact
from .access import PortalAccess

COOKIE = "__Host-kurumi"
DEFAULTS = dict(enabled=False, origin="", bind="127.0.0.1", port=8791)
ROOT = Path(__file__).resolve().parents[2] / "views" / "dashboard"
ASSETS = {
    "portal.js": "portal.js", "portal.css": "portal.css",
    "replay-panel.js": "replay-panel.js", "replay.css": "replay.css",
    "lightweight-charts.js": "vendor/lightweight-charts.js",
    "LICENSE-lightweight-charts.txt": "vendor/LICENSE-lightweight-charts.txt",
    "NOTICE.txt": "vendor/NOTICE.txt",
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


def settings(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise ValueError("面板设置无效")
    config = DEFAULTS | values
    if type(config["enabled"]) is not bool:
        raise ValueError("面板启用选项无效")
    if config["bind"] not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("面板监听地址无效")
    if type(config["port"]) is not int or not 1024 <= config["port"] <= 65535:
        raise ValueError("面板端口须在 1024～65535 之间")
    if not isinstance(config["origin"], str) or len(config["origin"]) > 250:
        raise ValueError("请输入面板 HTTPS 地址")
    raw = config["origin"].strip().rstrip("/")
    if raw or config["enabled"]:
        origin = urlsplit(raw)
        if (
            origin.scheme != "https" or not origin.hostname or origin.username is not None
            or origin.path or origin.query or origin.fragment or origin.port not in (None, 443)
            or ":" in origin.hostname
            or any(ch.isspace() for ch in raw) or "\\" in raw
        ):
            raise ValueError("请输入独立面板的 HTTPS 域名，例如 https://panel.example.com")
        config["origin"] = f"https://{origin.hostname.encode('idna').decode('ascii')}"
    else:
        config["origin"] = ""
    return config


class Portal:
    def __init__(self, plugin):
        self.plugin = plugin
        self.access = PortalAccess(plugin.engine)
        self.config = dict(DEFAULTS)
        self.runner = None
        self.lock = asyncio.Lock()
        self.review_slots = asyncio.Semaphore(4)
        self.error = ""

    def public(self):
        return dict(self.config, active=self.runner is not None, error=self.error)

    def link(self, owner, gid, mode):
        if self.runner is None or not self.config["enabled"]:
            raise ValueError("管理员尚未启用独立面板")
        return self.config["origin"] + "/#share=" + self.access.issue(owner, gid, mode)

    def app(self):
        @web.middleware
        async def boundary(request, handler):
            try:
                if request.method == "POST" and (
                    request.headers.get("Origin") != self.config["origin"]
                    or request.content_type != "application/json"
                ):
                    response = web.json_response({"error": "请求来源无效"}, status=403)
                else:
                    response = await handler(request)
            except web.HTTPException as exc:
                response = web.json_response({"error": "页面或操作不存在"}, status=exc.status)
            except (ValueError, TypeError, KeyError) as exc:
                message = str(exc) if isinstance(exc, ValueError) else "请求参数无效"
                response = web.json_response({"error": message}, status=400)
            except Exception:
                from astrbot.api import logger
                logger.warning("[Kurumi] 独立面板请求处理失败")
                response = web.json_response({"error": "面板暂不可用，请稍后重试"}, status=500)
            response.headers.update(SECURITY_HEADERS)
            return response

        app = web.Application(middlewares=[boundary], client_max_size=8192)
        app.add_routes([
            web.get("/", self.index), web.get("/assets/{file}", self.asset),
            web.post("/api/exchange", self.exchange), web.get("/api/session", self.session),
            web.post("/api/logout", self.logout), web.get("/api/review", self.review),
        ])
        return app

    async def open_listener(self, config):
        runner = web.AppRunner(self.app(), access_log=None, shutdown_timeout=5)
        await runner.setup()
        try:
            await web.TCPSite(runner, config["bind"], config["port"]).start()
        except BaseException:
            await runner.cleanup()
            raise
        return runner

    async def configure(self, config):
        async with self.lock:
            old = self.config
            same = self.runner and (config["bind"], config["port"]) == (old["bind"], old["port"])
            if not config["enabled"] or not same:
                await self.stop()
                if config["enabled"]:
                    try:
                        self.runner = await self.open_listener(config)
                    except OSError:
                        if old["enabled"]:
                            try:
                                self.runner = await self.open_listener(old)
                            except OSError:
                                self.error = "原面板端口也无法监听"
                        raise ValueError("无法监听面板端口，请检查端口是否被占用") from None
            if not config["enabled"] or old["origin"] and config["origin"] != old["origin"]:
                self.access.revoke_all()
            self.config = config
            self.error = ""

    async def stop(self):
        if self.runner:
            runner, self.runner = self.runner, None
            await runner.cleanup()

    async def index(self, request):
        return web.FileResponse(ROOT / "portal.html")

    async def asset(self, request):
        path = ASSETS.get(request.match_info["file"])
        if not path:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / path)

    async def payload(self, request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("请求内容须为对象")
        return body

    def cookie(self, response, token, ttl=3600):
        response.set_cookie(COOKIE, token, max_age=ttl, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    def identity(self, request):
        session = self.access.session(request.cookies.get(COOKIE, ""))
        if not session:
            raise web.HTTPUnauthorized()
        return session

    def game(self, request, session):
        gid = request.query.get("game") or session["game"]
        if gid != session["game"]:
            raise web.HTTPForbidden()
        return self.access.own(session["owner"], gid)

    async def exchange(self, request):
        token = self.access.exchange((await self.payload(request)).get("token"))
        self.access.logout(request.cookies.get(COOKIE, ""))
        return self.cookie(web.json_response({"ok": True}), token)

    async def session(self, request):
        session = self.access.session(request.cookies.get(COOKIE, ""))
        if not session:
            return web.json_response({"authenticated": False})
        game = self.game(request, session)
        return web.json_response(dict(
            authenticated=True, mode=session["mode"],
            games=[dict(id=game["id"], name=redact(game["name"]) if session["mode"] == "read" else "虚拟交易复盘", pairs=game["pairs"])],
        ))

    async def logout(self, request):
        self.access.logout(request.cookies.get(COOKIE, ""))
        return self.cookie(web.json_response({"ok": True}), "", ttl=0)

    async def review(self, request):
        session = self.identity(request)
        game = self.game(request, session)
        if self.review_slots.locked():
            return web.json_response({"error": "复盘请求较多，请稍后重试"}, status=429)
        async with self.review_slots:
            result = await review(
                self.plugin, game["id"], request.query.get("pair", ""),
                int(request.query.get("days", 1)), int(request.query.get("end", 0)),
                private=session["mode"] == "read",
            )
        if self.identity(request) != session:
            raise web.HTTPUnauthorized()
        self.game(request, session)
        return web.json_response(result)
