"""AstrBot lifecycle and authenticated View API."""

import asyncio
import json
from astrbot.api.star import StarTools
from astrbot.api.web import request, json_response, error_response

from ..core.engine import Engine, PAIRS, dump
from ..core.replay import review
from ..core.journal import journal
from ..market_data.market import Market, probe, signature, market_error
from ..market_data.settings import merge_settings, public_settings
from ..agent.decisions import DecisionService
from ..market_data.history import History, identity
from ..core.alerts import notices
from ..users.identity import Identity
from ..diary.scheduler import DiaryService
from .diary_api import DiaryApiMixin
from .settings_api import SettingsApiMixin
from .portal_api import PortalApiMixin
from ..portal.server import Portal, settings as portal_settings
from ..users import ownership, policy
from ..agent import llm
from ..notifications.service import NotificationService

NAME = "astrbot_plugin_kurumi_simulator"


class KurumiMixin(DiaryApiMixin, SettingsApiMixin, PortalApiMixin):
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
        self.portal = Portal(self)
        self.instance_locks = {}
        self.history = History(self.engine, self.market)
        self.history_warmed = set()
        self.market_lock = asyncio.Lock()
        self.tasks = set()
        self.runtime_error = ""
        for route, handler, methods in (
            ("state", self.web_state, ["GET"]),
            ("review", self.web_review, ["GET"]),
            ("journal", self.web_journal, ["GET"]),
            ("portal-settings", self.web_portal_settings, ["POST"]),
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
        config = None
        try:
            config = portal_settings(self.settings().get("portal", {}))
            await self.portal.configure(config)
        except ValueError as exc:
            if config is not None:
                self.portal.config = config
            self.portal.error = str(exc)
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
        await self.portal.stop()
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

    async def web_journal(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            gid = request.query.get("game", "")
            self.engine.get(gid)
            return json_response(journal(
                self.engine, gid, page=int(request.query.get("page", 1)),
                before=int(request.query.get("before", 0)), include_text=True,
                pair=request.query.get("pair", ""), source=request.query.get("source", "all"),
                filter=request.query.get("filter", "all"), sort=request.query.get("sort", "newest"),
            ))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    async def web_review(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        try:
            return json_response(await review(
                self, request.query.get("game", ""), request.query.get("pair", ""),
                int(request.query.get("days", 1)), int(request.query.get("end", 0)),
            ))
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)

    def workspace_mode(self, users):
        saved = self.settings().get("workspace_mode", {})
        ids = {user["id"] for user in users}
        main = saved.get("main_user_id")
        if main not in ids:
            main = next((user["id"] for user in users if user["instances"]), users[0]["id"] if users else "")
        return dict(multiplayer=saved.get("multiplayer", False), main_user_id=main,
                    role_settings=saved.get("role_settings"))

    async def web_state(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        gid = request.query.get("game", "")
        games = self.engine.games()
        users = self.engine.users()
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
                    users=[dict({key: value for key, value in user.items() if key != "public_id"},
                                portal_username=self.portal.accounts.username(user["id"])) for user in users],
                    mode=self.workspace_mode(users),
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
                portal=self.portal.public(),
                portal_instance=self.portal_instance(gid) if exists else None,
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

    async def validate_persona(self, persona):
        if not isinstance(persona, str) or not persona.strip():
            raise ValueError("请选择 AstrBot 人格后再开始游戏")
        persona = persona.strip()
        if not any(p.persona_id == persona for p in self.context.persona_manager.personas):
            raise ValueError("所选人格不存在，请重新选择")
        if not await self.context.persona_manager.get_persona(persona):
            raise ValueError("所选人格不存在，请重新选择")
        return persona

    async def web_command(self):
        if not self.authorized():
            return error_response("需要 AstrBot 登录", status_code=401)
        body = await request.json(default=None)
        try:
            if not isinstance(body, dict):
                raise ValueError("请求必须为对象")
            if body.get("action") in ("pause", "resume"):
                raise ValueError("暂停按钮已移除，请在实例设置中管理定时自主看盘")
            if body.get("action") == "update_pairs":
                return json_response(self.engine.update_pairs(body["game"], body.get("pairs")))
            if body.get("action") == "create":
                options = body.get("options", {})
                if not isinstance(options, dict):
                    raise ValueError("实例设置须为对象")
                options = dict(options)
                mode = self.workspace_mode(self.engine.users())
                options["_role_settings"] = mode["role_settings"]
                options["_main_user_id"] = mode["main_user_id"]
                options["_issue_user_token"] = False
                binding = options.get("user_binding")
                if not isinstance(binding, dict) or binding.get("type") != "umo":
                    raise ValueError("新建实例只能使用私聊 UMO 绑定")
                if not isinstance(binding.get("values"), list) or len(binding["values"]) != 1:
                    raise ValueError("每位用户只能绑定一个私聊 UMO")
                options["persona"] = await self.validate_persona(options.get("persona"))
                options.setdefault("auto", True)
                if type(options["auto"]) is not bool:
                    raise ValueError("定时看盘开关须为布尔值")
                if options["auto"]:
                    llm.ensure_available(self, options)
                return json_response(self.engine.create(options))
            if body.get("action") == "workspace_mode":
                multiplayer = body.get("multiplayer")
                main = body.get("main_user_id", "")
                with self.engine.transaction():
                    users = self.engine.users()
                    if type(multiplayer) is not bool or (
                        main not in {user["id"] for user in users} and (main or users)
                    ):
                        raise ValueError("请选择有效的主用户")
                    saved = self.settings()
                    prior = saved.get("workspace_mode", {})
                    templates = body.get("role_settings", prior.get("role_settings"))
                    if templates is not None:
                        if not isinstance(templates, dict) or set(templates) != {"main", "others"}:
                            raise ValueError("请同时提供主用户和其他用户的设置")
                        if any(not isinstance(value, dict) or set(value) != {"policy", "notifications"} for value in templates.values()):
                            raise ValueError("角色权限或通知设置字段无效")
                        templates = {
                            role: dict(policy=policy.validate(values["policy"]),
                                       notifications=policy.notification_settings(values["notifications"]))
                            for role, values in templates.items()
                        }
                        previous_main = self.workspace_mode(users)["main_user_id"]
                        for user in users:
                            uid = user["id"]
                            role = "main" if uid == main else "others"
                            if templates[role] != (prior.get("role_settings") or {}).get(role) or (uid == main) != (uid == previous_main):
                                values = templates[role]
                                policy.apply(self.engine, uid, user["name"], values["policy"], values["notifications"])
                    saved["workspace_mode"] = dict(multiplayer=multiplayer, main_user_id=main, role_settings=templates)
                    self.engine.db.execute(
                        "INSERT OR REPLACE INTO settings VALUES(1,?)", (dump(saved),)
                    )
                return json_response({"ok": True})
            if body.get("action") == "update_user_umo":
                uid = str(body.get("user_id", ""))
                binding = ownership.normalize(dict(type="umo", values=[body.get("umo")]))
                umo = binding["values"][0]
                alias = "umo:" + umo
                with self.engine.transaction():
                    if not self.engine.db.execute("SELECT 1 FROM sim_users WHERE id=?", (uid,)).fetchone():
                        raise ValueError("用户不存在")
                    row = self.engine.db.execute("SELECT user_id FROM sim_user_aliases WHERE alias=?", (alias,)).fetchone()
                    portal_owner = self.portal.accounts.owner_for_umo(umo)
                    if (row and row[0] != uid) or (portal_owner and portal_owner != uid):
                        raise ValueError("此 UMO 已绑定其他用户")
                    self.engine.db.execute(
                        "DELETE FROM sim_user_aliases WHERE user_id=? AND alias LIKE 'umo:%' AND alias<>?",
                        (uid, alias),
                    )
                    self.engine.db.execute("INSERT OR IGNORE INTO sim_user_aliases VALUES(?,?)", (alias, uid))
                    self.portal.accounts.sync_username(uid, umo)
                    self.engine.db.execute("DELETE FROM sim_reference_grants WHERE user_id=? AND umo<>?", (uid, umo))
                    for game in self.engine.games():
                        if game.get("owner_id") != uid:
                            continue
                        game.update(user_binding=binding, reference_umo=umo, umo=umo)
                        game["action_revision"] = game.get("action_revision", 0) + 1
                        self.engine.save(game)
                return json_response({"ok": True})
            if body.get("action") == "set_portal_password":
                username = await self.portal.accounts.set_password(
                    str(body.get("user_id", "")), body.get("password")
                )
                return json_response(dict(ok=True, username=username))
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
            if body.get("action") == "delete":
                return json_response(self.engine.delete(body["game"]))
            if body.get("action") == "bind":
                game = self.engine.get(body["game"])
                provider, persona = (
                    str(body.get("provider", game.get("provider", ""))),
                    body.get("persona", game.get("persona", "")),
                )
                if (
                    llm.settings(self.settings().get("llm"))["mode"] == "platform"
                    and provider
                    and not self.context.get_provider_by_id(provider)
                ):
                    raise ValueError("模型不存在")
                persona = await self.validate_persona(persona)
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
