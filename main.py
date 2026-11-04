"""AstrBot discovered entry point."""

from astrbot.api.event import filter
from astrbot.api.star import Star

from .src.plugin import KurumiMixin
from .src.tool_register import register_tools


class KurumiSimulator(KurumiMixin, Star):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        register_tools(self)

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
