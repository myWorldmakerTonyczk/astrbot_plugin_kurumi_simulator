"""AstrBot discovered entry point."""

from astrbot.api.star import Star
from astrbot.api.event import AstrMessageEvent, filter
from .src.plugin import KurumiMixin
from .src.tools import console, read_logs, list_instances, select_instance
from .src.engine import dump


class KurumiSimulator(KurumiMixin, Star):
    @filter.llm_tool(name="kurumi_forex")
    async def forex(
        self,
        event: AstrMessageEvent,
        action: str,
        parameters: str = "{}",
        user_id: str = "",
    ) -> str:
        """在绑定的纯虚拟外汇账户查盘、交易或读取长期交易日志。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            action(string): state查账户及行情，logs查日志，open开仓，close平仓，observe观望，plan更新计划，计划使用kurumi_write_plan，笔记暂不修改。
            parameters(string): JSON对象。操作必须含reason理由；open含pair如EUR/USD、side为buy或sell、units基础货币数量，可填sl/tp价格；close含position持仓ID；plan/notes含text；logs可填before日志ID。先state查询规则和有效报价，未成功不得声称成交。
        """
        return await console(self, event, action, parameters, user_id)

    @filter.llm_tool(name="kurumi_watch_market")
    async def watch_market(self, event: AstrMessageEvent, user_id: str = "") -> str:
        """查看绑定游戏的真实报价、账户、持仓、费用、交易规则、持仓计划与近期日志。
        操作前先查盘；market_error 或报价过期时不能假装已经成交。资金全部为虚拟。

        Args:
            user_id(string): 随机ID方式每次调用携带完整ID，QQ/UMO绑定可留空。
        """
        return await console(self, event, "state", "{}", user_id)

    @filter.llm_tool(name="kurumi_read_journal")
    async def read_journal(
        self,
        event: AstrMessageEvent,
        pair: str = "",
        before: int = 0,
        limit: int = 20,
        user_id: str = "",
    ) -> str:
        """查询人类、AI及系统的统一交易日志，可用于复盘和了解追加本金。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            pair(string): 可选货币对如EUR/USD；留空查询所有类型，包括追加本金。
            before(number): 分页游标，查询该日志ID之前的记录；0表示最新。
            limit(number): 返回条数，1到50，默认20。
        """
        return await read_logs(self, event, pair, before, limit, user_id)

    @filter.llm_tool(name="kurumi_open_position")
    async def open_position(
        self,
        event: AstrMessageEvent,
        pair: str,
        side: str,
        units: float,
        reason: str,
        stop_loss: float = 0,
        take_profit: float = 0,
        user_id: str = "",
    ) -> str:
        """用虚拟资金开仓。同一货币对支持多笔独立持仓；反向开仓是新增仓位，不自动平旧仓。成功及拒绝均记日志。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            pair(string): 允许的货币对，如EUR/USD，先调用看盘工具确认。
            side(string): buy表示看涨，sell表示看跌。
            units(number): 基础货币数量，不是手数，必须大于零。
            reason(string): 必填简短决策理由概要。
            stop_loss(number): 可选止损价格，0表示不设。
            take_profit(number): 可选止盈价格，0表示不设。
        """
        return await console(
            self,
            event,
            "open",
            dump(
                dict(
                    pair=pair,
                    side=side,
                    units=units,
                    reason=reason,
                    sl=stop_loss,
                    tp=take_profit,
                )
            ),
            user_id,
        )

    @filter.llm_tool(name="kurumi_close_position")
    async def close_position(
        self, event: AstrMessageEvent, position_id: str, reason: str, user_id: str = ""
    ) -> str:
        """平掉指定虚拟持仓，结算盈亏与手续费，并记录理由。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            position_id(string): 看盘工具返回的持仓id，不能填写货币对代替。
            reason(string): 本次平仓的简短理由。
        """
        return await console(
            self,
            event,
            "close",
            dump(dict(position=position_id, reason=reason)),
            user_id,
        )

    @filter.llm_tool(name="kurumi_set_protection")
    async def set_protection(
        self,
        event: AstrMessageEvent,
        position_id: str,
        reason: str,
        stop_loss: float = -1,
        take_profit: float = -1,
        user_id: str = "",
    ) -> str:
        """为已有持仓设置或修改止损、止盈。达到条件后由程序执行，不等待模型再次判断。
        此工具不是价格提醒线；价格事件唤醒还未实现。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            position_id(string): 看盘工具返回的持仓id。
            reason(string): 设置或调整保护线的理由概要。
            stop_loss(number): 止损价；-1保留原设置，0取消止损，正数设置新价格。
            take_profit(number): 止盈价；-1保留原设置，0取消止盈，正数设置新价格。
        """
        return await console(
            self,
            event,
            "protect",
            dump(
                dict(position=position_id, reason=reason, sl=stop_loss, tp=take_profit)
            ),
            user_id,
        )

    @filter.llm_tool(name="kurumi_write_memory")
    async def write_memory(
        self,
        event: AstrMessageEvent,
        kind: str,
        text: str,
        reason: str,
        user_id: str = "",
    ) -> str:
        """兼容入口，仅保存交易计划，操作会记入交易日志。不能改写成交事实。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            kind(string): 仅plan，笔记暂不扩展。
            text(string): 新的完整计划或经验，最多6000字符；保留仍有价值的已有内容。
            reason(string): 本次更新的简短说明。
        """
        if kind != "plan":
            return "未执行：笔记暂不扩展，计划请使用kurumi_write_plan。"
        return await console(
            self, event, kind, dump(dict(text=text, reason=reason)), user_id
        )

    @filter.llm_tool(name="kurumi_virtual_loan")
    async def virtual_loan(
        self,
        event: AstrMessageEvent,
        action: str,
        amount: float,
        reason: str,
        user_id: str = "",
    ) -> str:
        """在由人类启用的本局虚拟贷款额度内借款或还款。借入不算收益，债务和利息抵减净值。

        Args:
            user_id(string): 随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。
            action(string): borrow借款，repay还款；不能自行启用贷款或提高额度。
            amount(number): 虚拟美元金额，必须大于零；还款先偿利息。
            reason(string): 本次借还款的理由概要。
        """
        if action not in ("borrow", "repay"):
            return "未执行：只允许borrow或repay。"
        return await console(
            self, event, action, dump(dict(amount=amount, reason=reason)), user_id
        )

    @filter.llm_tool(name="kurumi_my_instances")
    async def my_instances(self, event: AstrMessageEvent, user_id: str = "") -> str:
        """查找当前用户有权操作的交易实例，不读取其他用户的盘。

        Args:
            user_id(string): 用户提供的随机ID；随机ID模式每次工具调用都须携带。QQ/UMO自动绑定可留空。
        """
        return await list_instances(self, event, user_id)

    @filter.llm_tool(name="kurumi_select_instance")
    async def select_instance(
        self, event: AstrMessageEvent, instance_id: str, user_id: str = ""
    ) -> str:
        """选择当前私聊要操作的实例，同一用户多个盘时先选择，不能选择他人的盘。

        Args:
            instance_id(string): 实例列表返回的完整ID或从1开始的序号。
            user_id(string): 随机用户ID，每次工具调用携带；QQ/UMO自动绑定可留空。
        """
        return await select_instance(self, event, instance_id, user_id)

    @filter.llm_tool(name="kurumi_write_plan")
    async def write_plan(
        self, event: AstrMessageEvent, text: str, reason: str, user_id: str = ""
    ) -> str:
        """随时保存当前实例的完整交易计划，跨聊天和后台看盘保留，并记录修改理由。先读取旧计划，保留有效内容；不修改笔记。

        Args:
            text(string): 完整计划，1～6000字。
            reason(string): 这次调整计划的简短理由概要。
            user_id(string): 随机ID模式每次调用携带完整ID，QQ/UMO自动绑定可留空。
        """
        return await console(
            self, event, "plan", dump(dict(text=text, reason=reason)), user_id
        )

    @filter.llm_tool(name="kurumi_price_history")
    async def price_history(
        self,
        event: AstrMessageEvent,
        pair: str,
        period: str = "1h",
        limit: int = 80,
        user_id: str = "",
    ) -> str:
        """读取真实历史K线辅助判断，不会下单。

        Args:
            pair(string): 货币对，例如EUR/USD。
            period(string): 1m、5m、15m、1h、4h、1d、1w、1M。
            limit(number): 10～200条，默认80。
            user_id(string): 随机ID模式每次携带完整ID，QQ/UMO绑定可留空。
        """
        return await console(
            self,
            event,
            "history",
            dump(dict(pair=pair, period=period, limit=limit)),
            user_id,
        )

    @filter.on_llm_request()
    async def trading_context(self, event, request):
        marker = "[久留美交易工具说明]"
        request.system_prompt = request.system_prompt or ""
        if marker in request.system_prompt:
            return
        request.system_prompt += (
            "\n"
            + marker
            + "交易全部为虚拟。用户提供随机用户ID时，调用每个kurumi工具都通过user_id参数携带，不得编造、回显或写入交易理由。先kurumi_my_instances查找本用户实例，多个时kurumi_select_instance选择，再查盘/日志和操作。交易计划通过kurumi_write_plan保存。操作必须写简短理由，工具失败不算成交。"
        )
