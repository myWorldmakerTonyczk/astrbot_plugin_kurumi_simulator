"""AstrBot lifecycle and authenticated View API."""

import asyncio
import json
from astrbot.api.star import StarTools
from astrbot.api.web import request, json_response, error_response

from ..core.engine import Engine, PAIRS, dump
from ..market_data.market import Market, probe, signature, market_error
from ..market_data.settings import merge_settings, public_settings
from ..agent.decisions import DecisionService
from ..market_data.history import History, identity
from ..core.alerts import notices
from ..users.identity import Identity
from ..diary.scheduler import DiaryService
from .diary_api import DiaryApiMixin
from .settings_api import SettingsApiMixin
from ..users import policy
from ..agent import llm
from ..notifications.service import NotificationService

NAME = "astrbot_plugin_kurumi_simulator"


class KurumiMixin(DiaryApiMixin, SettingsApiMixin):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        self.context, self.config = context, config
        path = StarTools.get_data_dir(NAME)
        path.mkdir(parents=True, exist_ok=True)
        self.engine = Engine(path / "ledger.sqlite3")
        self.engine.db.execute(
            "CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, data TEXT)"
        )
        self.market = Market(self.engine)
        self.identity = Identity(self.engine)
        self.diary = DiaryService(self)
        self.notifications = NotificationService(self)
        self.decisions = DecisionService(self)
        self.instance_locks = {}
        self.history = History(self.engine, self.market)
        self.history_warmed = set()
        self.market_lock = asyncio.Lock()
        self.tasks = set()
        self.runtime_error = ""
        for route, handler, methods in (
            ("state", self.web_state, ["GET"]),
            ("decision-settings", self.web_decision_settings, ["POST"]),
            ("llm-settings", self.web_llm_settings, ["POST"]),
            ("diaries", self.web_diaries, ["GET"]),
            ("diary-settings", self.web_diary_settings, ["POST"]),
            ("alerts", self.web_alerts, ["GET"]),
            ("history", self.web_history, ["GET"]),
            ("command", self.web_command, ["POST"]),
            ("settings", self.web_settings, ["POST"]),
            ("connection-test", self.web_connection_test, ["POST"]),
            ("decision", self.web_decision, ["POST"]),
        ):
            context.register_web_api(
                f"/{NAME}/{route}", handler, methods, "久留美模拟器 " + route
            )

    def settings(self):
        row = self.engine.db.execute("SELECT data FROM settings WHERE id=1").fetchone()
        settings = json.loads(row[0]) if row else {}
        settings.setdefault("history_source", "frankfurter")
        return settings

    def authorized(self):
        # Fail closed even if a host integration accidentally exposes a route.
        return bool(getattr(request, "username", None))

    async def initialize(self):
        self.spawn(self.loop())
        self.spawn(self.diary.loop())
        self.spawn(self.notifications.loop())
        self.spawn(self.decisions.loop())

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def terminate(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.engine.db.close()

    async def loop(self):
        while True:
            try:
                async with self.market_lock:
                    settings = self.settings()
                    await self.market.refresh(settings)
                    self.history.record(settings)
                    feed = identity(settings)
                    if feed not in self.history_warmed:
                        self.history_warmed.add(feed)
                        self.spawn(self.warm_history(settings))
                for game in self.engine.games():
                    try:
                        self.engine.tick(game["id"])
                    except ValueError:
                        continue  # No valid quote means no fabricated execution.
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.market.error = market_error(exc)
            await asyncio.sleep(10)

    async def warm_history(self, settings):
        await asyncio.gather(
            *(
                self.history.page(
                    settings,
                    pair,
                    "1d" if settings.get("history_source") == "frankfurter" else "5m",
                )
                for pair in PAIRS
            ),
            return_exceptions=True,
        )

    async def web_alerts(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            after = request.query.get("after")
            return json_response(
                notices(
                    self.engine,
                    request.query.get("game", ""),
                    int(after) if after is not None else None,
                )
            )
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    async def web_history(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            pair = request.query.get("pair", "")
            period = request.query.get("period", "5m")
            before = int(request.query.get("before", "0"))
            limit = int(request.query.get("limit", "200"))
            settings = self.settings()
            history_source = request.query.get(
                "history_source", settings.get("history_source", "frankfurter")
            )
            if history_source not in ("market", "frankfurter"):
                raise ValueError("历史来源无效")
            settings = dict(settings, history_source=history_source)
            result = await self.spawn(
                self.history.page(settings, pair, period, before, limit)
            )
            return json_response(result)
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception:
            return error_response(
                "历史行情获取失败，请检查来源连接后重试", status_code=400
            )

    async def web_state(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        gid = request.query.get("game", "")
        games = self.engine.games()
        exists = any(game["id"] == gid for game in games)
        providers = [
            dict(id=p.meta().id, name=p.meta().id)
            for p in self.context.get_all_providers()
        ]
        personas = [
            dict(id=p.persona_id, name=p.persona_id)
            for p in self.context.persona_manager.personas
        ]
        return json_response(
            dict(
                games=games,
                missing_instance=bool(gid) and not exists,
                workspace=dict(
                    users=self.engine.users(),
                    ownership_enforced=True,
                    dashboard_admin=True,
                ),
                current=self.engine.snapshot(gid) if exists else None,
                pairs=PAIRS,
                providers=providers,
                personas=personas,
                market_error=self.market.error,
                runtime_error=(
                    self.engine.get(gid).get("last_analysis_error", "")
                    if exists
                    else ""
                ),
                connection=public_settings(self.settings()),
                diary_settings=self.diary.config(),
                decision_limits=self.decisions.config(),
                decision=self.decisions.state(gid) if exists else None,
                llm_settings=llm.public(self.settings().get("llm")),
                instance_access=policy.effective(self.engine, self.engine.get(gid))
                if exists
                else None,
                market_identity=identity(self.settings()),
                history_feeds={
                    kind: identity(dict(self.settings(), history_source=kind))
                    for kind in ("market", "frankfurter")
                },
            )
        )

    async def web_command(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        body = await request.json(default=None)
        try:
            if not isinstance(body, dict):
                raise ValueError("请求必须为对象")
            if body.get("action") in ("pause", "resume"):
                raise ValueError("暂停按钮已移除，请在实例设置中管理定时自主看盘")
            if body.get("action") == "create":
                options = body.get("options", {})
                if not isinstance(options, dict) or "user_binding" not in options:
                    raise ValueError(
                        "绑定用户为必填，请填写QQ号、完整会话UMO列表或选择随机用户ID"
                    )
                return json_response(self.engine.create(options))
            if body.get("action") == "create_user":
                return json_response(
                    self.engine.create_virtual_user(body.get("nickname", ""))
                )
            if body.get("action") == "delete_user":
                return json_response(
                    self.engine.delete_virtual_user(str(body.get("user_id", "")))
                )
            if body.get("action") == "update_user":
                return json_response(
                    policy.update(
                        self.engine,
                        str(body.get("user_id", "")),
                        body.get("nickname"),
                        body.get("policy"),
                        body.get("notifications"),
                    )
                )
            if body.get("action") == "notifications":
                return json_response(
                    policy.change_notices(
                        self, body["game"], body.get("settings"), "human"
                    )
                )
            if body.get("action") == "rotate_user_id":
                return json_response(
                    self.engine.rotate_user_id(str(body.get("user_id", "")))
                )
            if body.get("action") == "delete":
                return json_response(self.engine.delete(body["game"]))
            if body.get("action") == "bind":
                game = self.engine.get(body["game"])
                provider, persona = (
                    str(body.get("provider", "")),
                    str(body.get("persona", "")),
                )
                if (
                    llm.settings(self.settings().get("llm"))["mode"] == "platform"
                    and provider
                    and not self.context.get_provider_by_id(provider)
                ):
                    raise ValueError("模型不存在")
                if persona:
                    await self.context.persona_manager.get_persona(persona)
                access = policy.effective(self.engine, game)
                interval = int(body.get("interval", access["effective_interval"]))
                if (
                    not access["allow_custom_interval"]
                    and interval != access["interval"]
                ):
                    raise ValueError(
                        "管理员未允许在实例面板修改看盘间隔，请在用户与权限中设置"
                    )
                history_count = int(body.get("history_count", 20))
                if not 0 <= history_count <= 100:
                    raise ValueError("聊天记录条数须在0～100之间")
                reference_umo = str(body.get("umo", "")).strip()
                if (
                    reference_umo
                    and game.get("owner_id")
                    and not self.identity.can_reference(game["owner_id"], reference_umo)
                ):
                    raise ValueError(
                        "请先在该私聊中通过交易工具选择此实例，或填写此用户已绑定的UMO"
                    )
                if (
                    not 600 <= interval <= 86400
                    or type(body.get("auto", False)) is not bool
                ):
                    raise ValueError("看盘间隔须在600～86400秒之间（最少10分钟）")
                if body.get("auto"):
                    if not persona:
                        raise ValueError("开启自动看盘前请选择人格")
                    llm.ensure_available(self, dict(game, provider=provider))
                with self.engine.transaction():
                    game = self.engine.get(body["game"])
                    if access["allow_custom_interval"] and game.get("owner_id"):
                        policy.sync_interval(self.engine, game["owner_id"], interval)
                        game = self.engine.get(body["game"])
                    game.update(
                        provider=provider,
                        persona=persona,
                        interval=interval,
                        history_count=history_count,
                        reference_umo=reference_umo,
                        auto=body.get("auto", False),
                    )
                    game["umo"] = str(body.get("umo", ""))[:300]
                    game["action_revision"] = game.get("action_revision", 0) + 1
                    self.engine.save(game)
                    self.engine.log(
                        game,
                        "human",
                        "bind",
                        "调整 AI 看盘设置",
                        {"provider": provider, "persona": persona},
                    )
                return json_response({"ok": True})
            result = self.engine.action(
                body["game"],
                body["action"],
                body.get("params", {}),
                "human",
                body.get("request_id"),
            )
            return json_response(result)
        except (ValueError, KeyError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    async def web_settings(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        body = await request.json(default=None)
        try:
            async with self.market_lock:
                old = self.settings()
                settings = merge_settings(old, body)
                changed = signature(old) != signature(settings)
                if changed and any(
                    g["positions"] or g["orders"] for g in self.engine.games()
                ):
                    raise ValueError(
                        "当前仍有持仓或挂单，请先结清再切换行情源或地址，避免不同报价制造盈亏。可以先使用连通性测试。"
                    )
                with self.engine.transaction():
                    self.engine.db.execute(
                        "INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(settings),)
                    )
                    if changed:
                        for game in self.engine.games():
                            if game["status"] == "ended":
                                continue
                            game["action_revision"] = game.get("action_revision", 0) + 1
                            self.engine.save(game)
                            self.engine.log(
                                game,
                                "human",
                                "market_source",
                                "修改行情连接，旧决策作废",
                                {},
                            )
                if changed:
                    self.engine.quotes.clear()
                self.market.error = "设置已保存，正在连接行情"
            return json_response(
                {
                    "ok": True,
                    "message": "行情设置已保存，后台将自动连接；可点击测试检查服务器连通性。",
                }
            )
        except ValueError as exc:
            return error_response(str(exc), status_code=400)

    async def web_connection_test(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        body = await request.json(default=None)
        try:
            settings = merge_settings(self.settings(), body)
            # Uses an isolated quote cache; never changes saved settings or account prices.
            return json_response(await probe(settings))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            return error_response(market_error(exc), status_code=400)

    async def web_decision(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            body = await request.json(default=None)
            if not isinstance(body, dict) or not isinstance(body.get("game"), str):
                raise ValueError("请选择交易实例")
            result = self.decisions.request_manual(body["game"])
            return json_response(
                dict(
                    ok=True,
                    message="看盘任务已排队，可在面板查看进度。",
                    decision=result,
                )
            )
        except (ValueError, TypeError, KeyError) as exc:
            return error_response(str(exc), status_code=400)
