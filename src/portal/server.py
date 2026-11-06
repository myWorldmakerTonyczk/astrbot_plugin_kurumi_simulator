"""Separate, opt-in web listener with its own browser identity boundary."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from ..core.replay import review
from ..core.journal import journal
from ..diary.store import redact
from .access import PortalAccess
from .accounts import ACCOUNT_TTL, PortalAccounts
from .operations import Operations

COOKIE = "__Host-kurumi"
DEFAULTS = dict(enabled=False, origin="", bind="127.0.0.1", port=8791)
ROOT = Path(__file__).resolve().parents[2] / "views" / "dashboard"
ASSETS = {
    "avatar.png": "assets/avatar.png",
    "hero-green.png": "assets/hero-green.png",
    "portal-kurumi-notebook.webp": "assets/portal-kurumi-notebook.webp",
    "portal-kurumi-journal.webp": "assets/portal-kurumi-journal.webp",
    "portal-kurumi.webp": "assets/portal-kurumi.webp",
    "portal-kurumi-header.webp": "assets/portal-kurumi-header.webp",
    "portal.js": "portal.js", "portal.css": "portal.css", "portal-trading.js": "portal-trading.js",
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


class Portal(Operations):
    def __init__(self, plugin):
        self.plugin = plugin
        self.access = PortalAccess(plugin.engine)
        self.accounts = PortalAccounts(self.access)
        self.config = dict(DEFAULTS)
        self.runner = None
        self.lock = asyncio.Lock()
        self.review_slots = asyncio.Semaphore(4)
        self.error = ""

    def public(self):
        return dict(self.config, active=self.runner is not None, error=self.error)

    async def account_link(self, owner):
        if self.runner is None or not self.config["enabled"]:
            raise ValueError("管理员尚未启用独立面板")
        username, password = await self.accounts.issue(owner)
        return self.config["origin"] + "/", username, password

    def link(self, owner, gid, mode):
        if self.runner is None or not self.config["enabled"]:
            raise ValueError("管理员尚未启用独立面板")
        return self.config["origin"] + "/#share=" + self.access.issue(owner, gid, mode)

    def app(self):
        @web.middleware
        async def boundary(request, handler):
            try:
                host = urlsplit(self.config["origin"]).netloc
                if request.host not in {host, host + ":443"} or (
                    request.method == "POST" and (
                        request.headers.get("Origin") != self.config["origin"]
                        or request.content_type != "application/json"
                    )
                ):
                    response = web.json_response({"error": "请求来源无效"}, status=403)
                else:
                    response = await handler(request)
            except web.HTTPException as exc:
                messages = {401: "请重新登录或领取链接", 403: "当前会话无权访问此实例或执行该操作", 413: "请求内容过大"}
                response = web.json_response({"error": messages.get(exc.status, "页面或操作不存在")}, status=exc.status)
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
            web.get("/", self.index), web.get("/api/health", self.health), web.get("/assets/{file}", self.asset),
            web.post("/api/exchange", self.exchange), web.get("/api/session", self.session),
            web.post("/api/logout", self.logout), web.get("/api/review", self.review),
            web.post("/api/login", self.login), web.get("/api/account", self.account_state),
            web.post("/api/action", self.action),
            web.get("/api/journal", self.journal), web.get("/api/notebook", self.notebook),
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

    async def health(self, request):
        return web.json_response(
            {"service": "kurumi-user-portal", "ok": True},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def index(self, request):
        return web.FileResponse(ROOT / "portal.html")

    async def asset(self, request):
        path = ASSETS.get(request.match_info["file"])
        if not path:
            raise web.HTTPNotFound()
        suffix = Path(path).suffix
        content_type = {".js": "text/javascript", ".css": "text/css", ".txt": "text/plain", ".webp": "image/webp", ".png": "image/png"}[suffix]
        return web.FileResponse(ROOT / path, headers={"Content-Type": content_type})

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
        if session["mode"] != "account" and gid != session["game"]:
            raise web.HTTPForbidden()
        if not gid:
            raise ValueError("请选择交易实例")
        try:
            return self.access.own(session["owner"], gid)
        except ValueError:
            raise web.HTTPForbidden() from None

    async def exchange(self, request):
        token = self.access.exchange((await self.payload(request)).get("token"))
        self.access.logout(request.cookies.get(COOKIE, ""))
        return self.cookie(web.json_response({"ok": True}), token)

    async def session(self, request):
        session = self.access.session(request.cookies.get(COOKIE, ""))
        if not session:
            return web.json_response({"authenticated": False})
        mode = session["mode"]
        if mode == "account":
            games = [g for g in self.plugin.engine.games() if g.get("owner_id") == session["owner"]]
        else:
            games = [self.game(request, session)]
        return web.json_response(dict(
            authenticated=True, mode=mode, games=[self.describe_game(game, mode) for game in games],
        ))

    async def login(self, request):
        body = await self.payload(request)
        username = body.get("username", "")
        if not isinstance(username, str) or len(username) > 300:
            raise ValueError("账号格式无效")
        username = username.strip()
        if self.accounts.hash_slots.locked() or not self.accounts.rate_limit(username):
            return web.json_response({"error": "登录尝试过多，请稍后再试"}, status=429)
        origin = self.config["origin"]
        token = await self.accounts.login(username, body.get("password"))
        if token and origin != self.config["origin"]:
            self.access.logout(token)
            raise web.HTTPUnauthorized()
        if not token:
            return web.json_response({"error": "账号或密码不正确"}, status=401)
        self.access.logout(request.cookies.get(COOKIE, ""))
        return self.cookie(web.json_response({"ok": True}), token, ttl=ACCOUNT_TTL)

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
                private=session["mode"] != "summary",
            )
        if self.identity(request) != session:
            raise web.HTTPUnauthorized()
        self.game(request, session)
        return web.json_response(result)

    def records_game(self, request):
        session = self.identity(request)
        if session["mode"] == "summary":
            raise web.HTTPForbidden()
        return self.game(request, session)

    async def journal(self, request):
        game = self.records_game(request)
        result = journal(
            self.plugin.engine, game["id"], page=int(request.query.get("page", 1)),
            before=int(request.query.get("before", 0)), filter=request.query.get("filter", "all"),
        )
        result["logs"] = [
            dict(time=row["created"], action=row["action"], source=row["source"], status=row["status"],
                 reason=redact(row.get("reason") or ""))
            for row in result["logs"]
        ]
        return web.json_response(result)

    async def notebook(self, request):
        game = self.records_game(request)
        db = self.plugin.engine.db
        diaries = db.execute(
            """SELECT day,content FROM diaries WHERE game=? AND status='success'
               ORDER BY day DESC LIMIT 31""", (game["id"],)
        ).fetchall()
        return web.json_response(dict(
            plan=redact(game.get("plan") or ""),
            diaries=[dict(day=row[0], content=redact(row[1] or "")) for row in diaries],
        ))
