"""Deterministic paper ledger. No broker order endpoint exists in this project."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from ..users import ownership
from .replay_records import decision_scope, initialize as initialize_replay, sample

PAIRS = ("EUR/USD", "GBP/USD", "AUD/USD", "USD/JPY", "USD/CHF", "USD/CAD")


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("数值格式错误") from None
    if not result.is_finite() or abs(result) > Decimal("1e12"):
        raise ValueError("数值超出范围")
    return result


def positive(value):
    result = number(value)
    if result <= 0:
        raise ValueError("金额、数量和价格必须大于零")
    return result


def loan_debt(game, now=None):
    now = (
        game.get("loan_last", time.time())
        if game.get("status") == "ended"
        else time.time()
        if now is None
        else now
    )
    principal = number(game.get("loan_principal", 0))
    interest = number(game.get("loan_interest", 0))
    rate = number(game.get("loan_rate", "0.0001"))
    elapsed = max(0, now - float(game.get("loan_last", now)))
    return principal + interest + principal * rate * number(elapsed) / 86400


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class Engine:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS logs(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL, created REAL NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests(game TEXT, key TEXT, result TEXT,
            PRIMARY KEY(game,key));
        """)
        ownership.initialize(self.db)
        initialize_replay(self.db)
        self.quotes = {}

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, gid):
        row = self.db.execute("SELECT data FROM games WHERE id=?", (gid,)).fetchone()
        if not row:
            raise ValueError("游戏不存在")
        return json.loads(row[0])

    def games(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM games")]

    def save(self, game):
        if self.db.execute(
            "SELECT 1 FROM sim_deleted_instances WHERE id=?", (game["id"],)
        ).fetchone():
            raise ValueError("实例已删除，不能写回")
        self.db.execute(
            "INSERT INTO games(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (game["id"], dump(game)),
        )

    def log(self, game, source, action, reason, detail, status="success"):
        entry = dict(
            source=source,
            action=action,
            reason=str(reason)[:2000],
            detail=detail,
            status=status,
            balance=game["balance"],
            created=time.time(),
        )
        scope = decision_scope.get()
        if source == "ai" and scope and scope[0] == game["id"]:
            entry["decision_id"] = scope[1]
        cursor = self.db.execute(
            "INSERT INTO logs(game,created,data) VALUES (?,?,?)",
            (game["id"], entry["created"], dump(entry)),
        )
        return dict(id=cursor.lastrowid, **entry)

    def logs(self, gid, before=2**63 - 1, limit=50, pair=""):
        return [
            dict(id=r[0], **json.loads(r[1]))
            for r in self.db.execute(
                "SELECT seq,data FROM logs WHERE game=? AND seq<? AND (?='' OR json_extract(data,'$.detail.position.pair')=?) ORDER BY seq DESC LIMIT ?",
                (gid, int(before), pair, pair, min(100, max(1, int(limit)))),
            )
        ]

    def create(self, options):
        initial = positive(options.get("initial", "10000"))
        pairs = options.get("pairs", ["EUR/USD"])
        if (
            not isinstance(pairs, list)
            or not pairs
            or any(p not in PAIRS for p in pairs)
        ):
            raise ValueError("请选择支持的货币对")
        leverage = positive(options.get("leverage", 100))
        if leverage > 100:
            raise ValueError("初版杠杆范围为 1～100")
        rules = options.get("rules", {})
        if not isinstance(rules, dict) or set(rules) - {
            "profit",
            "loss",
            "floor",
            "drawdown",
            "deadline",
        }:
            raise ValueError("游戏规则字段无效")
        rules = {k: str(positive(v)) for k, v in rules.items() if v not in ("", None)}
        fee = number(options.get("fee_rate", "0.00002"))
        if not 0 <= fee <= Decimal(".01"):
            raise ValueError("手续费率须在 0～0.01 之间")
        if type(options.get("loan_enabled", True)) is not bool:
            raise ValueError("贷款开关须为布尔值")
        if type(options.get("allow_deposit", True)) is not bool:
            raise ValueError("追加本金开关须为布尔值")
        game = dict(
            id=uuid.uuid4().hex,
            name=str(options.get("name", "小澪的外汇日记"))[:80],
            initial=str(initial),
            balance=str(initial),
            invested=str(initial),
            created=time.time(),
            pairs=list(dict.fromkeys(pairs)),
            leverage=str(leverage),
            fee_rate=str(fee),
            fees="0",
            positions=[],
            orders=[],
            rules=rules,
            status="running",
            auto=options.get("auto", False),
            provider=str(options.get("provider", "")),
            persona=str(options.get("persona", "")).strip(),
            umo="",
            interval=3600,
            last_decision=0,
            index="1",
            peak="1",
            drawdown="0",
            revision=0,
            plan="",
            notes="",
            outcome="",
            allow_deposit=options.get("allow_deposit", True),
            reference_umo="",
            history_count=20,
            loan_enabled=bool(options.get("loan_enabled", True)),
            loan_limit=str(positive(options.get("loan_limit", initial * 2))),
            loan_rate="0.0001",
            loan_principal="0",
            loan_interest="0",
            loan_last=time.time(),
            loan_cost="0",
        )
        with self.transaction():
            if "user_binding" in options:
                game.update(
                    ownership.resolve(
                        self.db,
                        options["user_binding"],
                        options.get("user_nickname", ""),
                    )
                )
            if game.get("user_binding", {}).get("type") == "umo":
                game["reference_umo"] = game["user_binding"]["values"][0]
            if game.get("owner_id"):
                from ..users.policy import for_user, notice_defaults

                user_policy = for_user(self.db, game["owner_id"])
                limit = user_policy["max_instances"]
                count = self.db.execute(
                    "SELECT count(*) FROM games WHERE json_extract(data,'$.owner_id')=?",
                    (game["owner_id"],),
                ).fetchone()[0]
                if limit and count >= limit:
                    raise ValueError("此用户的交易实例数量已达管理员设置的上限")
                game["interval"] = user_policy["interval"]
                game["notifications"] = notice_defaults(self.db, game["owner_id"])
            game["last_equity"] = str(initial)
            self.save(game)
            sample(self.db, game, force=True)
            self.log(game, "human", "create", "创建虚拟游戏", {"initial": str(initial)})
        return game

    def users(self):
        return ownership.users(self.db)

    def create_virtual_user(self, nickname=""):
        with self.transaction():
            owner = ownership.resolve(
                self.db, {"type": "random", "values": []}, nickname
            )
        return next(user for user in self.users() if user["id"] == owner["owner_id"])

    def rotate_user_id(self, uid):
        with self.transaction():
            token = ownership.issue_id(self.db, uid)
        return dict(ok=True, user_id=uid, public_id=token)

    def _delete_instance(self, gid):
        self.get(gid)
        self.db.execute(
            "INSERT INTO sim_deleted_instances VALUES(?,?)", (gid, time.time())
        )
        self.db.execute(
            "DELETE FROM sim_selections WHERE instance_id=?", (gid,)
        ) if self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='sim_selections'"
        ).fetchone() else None
        for table in ("logs", "requests"):
            self.db.execute(f"DELETE FROM {table} WHERE game=?", (gid,))
        self.db.execute("DELETE FROM games WHERE id=?", (gid,))

    def delete(self, gid):
        with self.transaction():
            self._delete_instance(gid)
        return dict(ok=True, deleted=gid)

    def delete_virtual_user(self, uid):
        with self.transaction():
            if not self.db.execute(
                "SELECT 1 FROM sim_users WHERE id=?", (uid,)
            ).fetchone():
                raise ValueError("用户不存在")
            ids = [g["id"] for g in self.games() if g.get("owner_id") == uid]
            for gid in ids:
                self._delete_instance(gid)
            for table in (
                "sim_selections",
                "sim_reference_grants",
                "sim_user_aliases",
                "sim_user_tokens",
                "sim_user_policy",
                "sim_user_notice_defaults",
            ):
                if self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    self.db.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
            self.db.execute("DELETE FROM sim_users WHERE id=?", (uid,))
        return dict(ok=True, deleted_user=uid, deleted_instances=ids)

    def quote(self, pair):
        q = self.quotes.get(pair)
        if not q or time.time() - q["timestamp"] > 30 or q.get("tradeable") is not True:
            raise ValueError(f"{pair} 行情过期、休市或尚未连接，暂停成交")
        return q

    def convert(self, amount, currency):
        if currency == "USD":
            return amount
        q = self.quote("USD/" + currency)
        return amount / ((number(q["bid"]) + number(q["ask"])) / 2)

    def valuation(self, game):
        floating, margin = Decimal(0), Decimal(0)
        rows = []
        for p in game["positions"]:
            q = self.quote(p["pair"])
            price = number(q["bid"] if p["side"] == "buy" else q["ask"])
            units = number(p["units"])
            pnl = self.convert(
                (price - number(p["entry"]))
                * units
                * (1 if p["side"] == "buy" else -1),
                p["pair"][4:],
            )
            used = self.convert(units * price, p["pair"][4:]) / number(
                p.get("leverage", game["leverage"])
            )
            floating += pnl
            margin += used
            rows.append(dict(**p, pnl=str(pnl), margin=str(used), current=str(price)))
        collateral = number(game["balance"]) + floating
        equity = collateral - loan_debt(game)
        return dict(
            equity=str(equity),
            floating=str(floating),
            margin=str(margin),
            free=str(collateral - margin),
            collateral=str(collateral),
            positions=rows,
            profit=str(equity - number(game["invested"])),
            debt=str(loan_debt(game)),
            return_rate=str((number(game["index"]) - 1) * 100),
        )

    def mark(self, game):
        equity = number(self.valuation(game)["equity"])
        previous = number(game.get("last_equity", game["initial"]))
        if previous > 0:
            game["index"] = str(
                number(game["index"]) * max(Decimal(0), equity) / previous
            )
        game["last_equity"] = str(equity)
        game["peak"] = str(max(number(game["peak"]), number(game["index"])))
        dd = (1 - number(game["index"]) / number(game["peak"])) * 100
        game["drawdown"] = str(max(number(game["drawdown"]), dd))

    def close_position(self, game, pid, reason, source, kind=""):
        p = next((p for p in self.valuation(game)["positions"] if p["id"] == pid), None)
        if not p:
            raise ValueError("持仓不存在")
        notional = self.convert(
            number(p["units"]) * number(p["current"]), p["pair"][4:]
        )
        fee = notional * number(game["fee_rate"])
        game["balance"] = str(number(game["balance"]) + number(p["pnl"]) - fee)
        game["fees"] = str(number(game["fees"]) + fee)
        game["positions"] = [r for r in game["positions"] if r["id"] != pid]
        self.log(
            game, source, "close", reason, dict(position=p, fee=str(fee), kind=kind)
        )

    def trade(self, game, body, source, reason):
        pair, side = body.get("pair"), body.get("side")
        if pair not in game["pairs"] or side not in ("buy", "sell"):
            raise ValueError("品种未授权或交易方向无效")
        leverage = positive(body.get("leverage", game["leverage"]))
        if leverage > number(game["leverage"]):
            raise ValueError("本次杠杆超过游戏上限")
        q = self.quote(pair)
        entry = number(q["ask"] if side == "buy" else q["bid"])
        if body.get("margin"):
            units = positive(body["margin"]) * leverage / self.convert(entry, pair[4:])
        else:
            units = positive(body.get("units"))
        sl = str(positive(body["sl"])) if body.get("sl") else ""
        tp = str(positive(body["tp"])) if body.get("tp") else ""
        if sl and (
            (side == "buy" and number(sl) >= entry)
            or (side == "sell" and number(sl) <= entry)
        ):
            raise ValueError("止损必须位于亏损方向")
        if tp and (
            (side == "buy" and number(tp) <= entry)
            or (side == "sell" and number(tp) >= entry)
        ):
            raise ValueError("止盈必须位于盈利方向")
        notional = self.convert(units * entry, pair[4:])
        fee = notional * number(game["fee_rate"])
        p = dict(
            id=uuid.uuid4().hex,
            pair=pair,
            side=side,
            units=str(units),
            entry=str(entry),
            leverage=str(leverage),
            sl=sl,
            tp=tp,
            reason=reason,
            created=time.time(),
        )
        game["balance"] = str(number(game["balance"]) - fee)
        game["fees"] = str(number(game["fees"]) + fee)
        game["positions"].append(p)
        if number(self.valuation(game)["free"]) < 0:
            raise ValueError("可用保证金不足，未成交")
        self.log(game, source, "open", reason, dict(position=p, fee=str(fee)))

    def action(self, gid, action, body, source="human", key=None):
        try:
            return self._action(gid, action, body, source, key)
        except ValueError as exc:
            # Preserve failed attempts without retaining any partial balance changes.
            game = self.get(gid)
            with self.transaction():
                self.log(
                    game,
                    source,
                    action,
                    str(body.get("reason", "未填写理由")),
                    {"error": str(exc), "request_id": key},
                    status="rejected",
                )
            raise

    def _action(self, gid, action, body, source="human", key=None):
        key = key or uuid.uuid4().hex
        with self.transaction():
            prior = self.db.execute(
                "SELECT result FROM requests WHERE game=? AND key=?", (gid, key)
            ).fetchone()
            if prior:
                return json.loads(prior[0])
            game = self.get(gid)
            reason = str(body.get("reason", "未填写理由"))[:2000]
            if source == "ai" and (not reason.strip() or reason == "未填写理由"):
                raise ValueError("AI 操作必须填写理由概要")
            if game["status"] not in ("running", "paused"):
                raise ValueError("本局已结束或等待结算")
            if source == "ai" and game["status"] != "running":
                raise ValueError("自主交易已暂停")
            if action in ("open", "close", "deposit", "borrow", "repay"):
                self.settle_interest(game)
                self.mark(game)
            if action == "open":
                self.trade(game, body, source, reason)
            elif action == "close":
                self.close_position(game, body.get("position"), reason, source)
            elif action == "protect":
                p = next(
                    (p for p in game["positions"] if p["id"] == body.get("position")),
                    None,
                )
                if not p:
                    raise ValueError("持仓不存在")
                q = self.quote(p["pair"])
                current = number(q["bid"] if p["side"] == "buy" else q["ask"])
                before = dict(sl=p["sl"], tp=p["tp"])
                for field in ("sl", "tp"):
                    value = number(body.get(field, -1))
                    if value == -1:
                        continue
                    if value < 0:
                        raise ValueError("保护价只能为-1、0或正数")
                    if value:
                        below = (p["side"] == "buy") == (field == "sl")
                        if (below and value >= current) or (
                            not below and value <= current
                        ):
                            raise ValueError(
                                "保护价已越过当前可成交价，请直接平仓或重新设置"
                            )
                    p[field] = str(value) if value else ""
                if before == dict(sl=p["sl"], tp=p["tp"]):
                    raise ValueError("保护线没有变化")
                self.log(
                    game, source, "protect", reason, {"position": p, "before": before}
                )
            elif action == "loan_config":
                if source != "human" or type(body.get("enabled")) is not bool:
                    raise ValueError("只有人类可以启用或禁用贷款")
                game["loan_enabled"] = body["enabled"]
                game.setdefault("loan_limit", str(number(game["initial"]) * 2))
                game.setdefault("loan_rate", "0.0001")
                self.log(game, source, action, reason, {"enabled": body["enabled"]})
            elif action == "borrow":
                if not game.get("loan_enabled", False):
                    raise ValueError("本局尚未由人类启用虚拟贷款")
                amount = positive(body.get("amount"))
                principal = number(game.get("loan_principal", 0))
                if principal + amount > number(
                    game.get("loan_limit", number(game["initial"]) * 2)
                ):
                    raise ValueError("超过本局虚拟贷款上限")
                game["loan_principal"] = str(principal + amount)
                game["balance"] = str(number(game["balance"]) + amount)
                self.log(
                    game,
                    source,
                    action,
                    reason,
                    {"amount": str(amount), "debt": str(loan_debt(game))},
                )
            elif action == "repay":
                debt = loan_debt(game)
                amount = min(positive(body.get("amount")), debt)
                if debt <= 0:
                    raise ValueError("没有待偿贷款")
                if amount > number(self.valuation(game)["free"]):
                    raise ValueError("可用保证金不足以偿还这笔金额，请先减仓")
                interest = number(game.get("loan_interest", 0))
                paid_interest = min(amount, interest)
                game["loan_interest"] = str(interest - paid_interest)
                game["loan_principal"] = str(
                    number(game.get("loan_principal", 0)) - (amount - paid_interest)
                )
                game["balance"] = str(number(game["balance"]) - amount)
                self.log(
                    game,
                    source,
                    action,
                    reason,
                    {
                        "amount": str(amount),
                        "interest_paid": str(paid_interest),
                        "debt": str(loan_debt(game)),
                    },
                )
            elif action == "deposit":
                if source != "human" or not game["allow_deposit"]:
                    raise ValueError("不允许 AI 自行追加本金")
                amount = positive(body.get("amount"))
                game["balance"] = str(number(game["balance"]) + amount)
                game["invested"] = str(number(game["invested"]) + amount)
                game["last_equity"] = str(number(game["last_equity"]) + amount)
                self.log(game, source, action, reason, {"amount": str(amount)})
            elif action in ("pause", "resume"):
                if source != "human":
                    raise ValueError("此操作需要人类管理权限")
                game["status"] = "paused" if action == "pause" else "running"
                self.log(game, source, action, reason, {})
            elif action in ("plan", "notes", "observe"):
                if action != "observe":
                    game[action] = str(body.get("text", ""))[:6000]
                self.log(game, source, action, reason, {"text": body.get("text", "")})
            else:
                raise ValueError("未知操作")
            game["revision"] += 1
            game["action_revision"] = game.get("action_revision", 0) + 1
            self.mark(game) if action in ("open", "close", "borrow", "repay") else None
            self.save(game)
            if action in {"open", "close", "deposit", "borrow", "repay"}:
                sample(self.db, game, force=True)
            result = {"ok": True, "revision": game["revision"], "request_id": key}
            self.db.execute(
                "INSERT INTO requests VALUES(?,?,?)", (gid, key, dump(result))
            )
            return result

    def settle_interest(self, game, now=None):
        now = time.time() if now is None else now
        debt = loan_debt(game, now)
        added = (
            debt
            - number(game.get("loan_principal", 0))
            - number(game.get("loan_interest", 0))
        )
        game["loan_interest"] = str(number(game.get("loan_interest", 0)) + added)
        game["loan_cost"] = str(number(game.get("loan_cost", 0)) + added)
        game["loan_last"] = now
        if added and now - float(game.get("loan_log_at", now)) >= 86400:
            self.log(
                game,
                "system",
                "loan_interest",
                "虚拟贷款按实际时间计息",
                {"total_interest": game["loan_cost"], "debt": str(debt)},
            )
            game["loan_log_at"] = now
        game.setdefault("loan_log_at", now)

    def tick(self, gid):
        with self.transaction():
            game = self.get(gid)
            if game["status"] == "ended":
                return
            self.settle_interest(game)
            original_positions = dump(game["positions"])
            original_status = game["status"]
            for p in list(game["positions"]):
                q = self.quote(p["pair"])
                price = number(q["bid"] if p["side"] == "buy" else q["ask"])
                stopped = p["sl"] and (
                    price <= number(p["sl"])
                    if p["side"] == "buy"
                    else price >= number(p["sl"])
                )
                taken = p["tp"] and (
                    price >= number(p["tp"])
                    if p["side"] == "buy"
                    else price <= number(p["tp"])
                )
                if stopped or taken:
                    self.close_position(
                        game, p["id"], "触发止损" if stopped else "触发止盈", "system"
                    )
            self.mark(game)
            v = self.valuation(game)
            # Gross trading collateral / used margin < 50%; debt is deducted for net returns.
            while (
                game["positions"] and number(v["collateral"]) < number(v["margin"]) / 2
            ):
                worst = min(v["positions"], key=lambda p: number(p["pnl"]))
                self.close_position(
                    game,
                    worst["id"],
                    "保证金水平低于50%，模拟强平",
                    "system",
                    kind="liquidation",
                )
                v = self.valuation(game)
            self.mark(game)
            needs_margin = bool(game["positions"]) and number(v["collateral"]) < number(
                v["margin"]
            )
            if needs_margin and not game.get("margin_call_active", False):
                self.log(
                    game,
                    "system",
                    "margin_call",
                    "保证金水平低于100%",
                    dict(
                        level=str(number(v["collateral"]) / number(v["margin"]) * 100),
                        shortfall=str(number(v["margin"]) - number(v["collateral"])),
                    ),
                )
            game["margin_call_active"] = needs_margin
            r, eq = game["rules"], number(v["equity"])
            ret = (number(game["index"]) - 1) * 100
            outcome = ""
            if (
                eq <= 0
                or ("floor" in r and eq <= number(r["floor"]))
                or ("loss" in r and number(v["profit"]) <= -number(r["loss"]))
                or (
                    "drawdown" in r
                    and number(game["drawdown"]) >= number(r["drawdown"])
                )
            ):
                outcome = "失败"
            elif "profit" in r and ret >= number(r["profit"]):
                outcome = "胜利"
            elif "deadline" in r and time.time() >= number(r["deadline"]):
                outcome = "到期"
            if outcome:
                for p in list(game["positions"]):
                    self.close_position(game, p["id"], "游戏结束结算", "system")
                game["status"], game["outcome"], game["auto"] = "ended", outcome, False
                self.mark(game)
                self.log(
                    game,
                    "system",
                    "end",
                    "触发游戏结束条件",
                    {"outcome": outcome, "bankrupt": eq <= 0},
                )
            game["revision"] += 1
            if (
                original_positions != dump(game["positions"])
                or original_status != game["status"]
            ):
                game["action_revision"] = game.get("action_revision", 0) + 1
            self.save(game)
            sample(self.db, game, force=original_positions != dump(game["positions"]) or original_status != game["status"])

    def snapshot(self, gid):
        game = self.get(gid)
        try:
            value = self.valuation(game)
            error = ""
        except ValueError as exc:
            value, error = None, str(exc)
        return dict(
            game=game,
            valuation=value,
            market_error=error,
            logs=self.logs(gid),
            quotes=self.quotes,
            pairs=PAIRS,
        )
