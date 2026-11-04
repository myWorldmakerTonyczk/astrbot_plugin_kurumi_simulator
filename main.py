"""AstrBot discovered entry point."""

from astrbot.api.event import filter
from astrbot.api.star import Star

from .src.integration.plugin import KurumiMixin
from .src.tools.registry import register_tools


class KurumiSimulator(KurumiMixin, Star):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        register_tools(self)

    @filter.on_llm_request()
    async def trading_context(self, event, request):
        self.capture_diary_chat(event, "user", event.get_message_str())
        marker = "[久留美交易工具说明]"
        request.system_prompt = request.system_prompt or ""
        if marker in request.system_prompt:
            return
        request.system_prompt += (
            "\n"
            + marker
            + "交易全部为虚拟。用户提供随机用户ID时，调用每个kurumi工具都通过user_id参数携带，不得编造、回显或写入交易理由。先kurumi_my_instances查找本用户实例，多个时kurumi_select_instance选择，再查盘/日志和操作。交易计划通过kurumi_write_plan保存，历史日记/经验通过kurumi_read_diary查询。操作必须写简短理由，工具失败不算成交。按用户意愿可用kurumi_set_notifications调整本实例主动通知，须管理员授权；所有主动消息遵守免打扰黑名单，不得绕过。"
        )

    def capture_diary_chat(self, event, role, text):
        try:
            if self.diary.config()["enabled"]:
                self.diary.store.capture(self, event, role, text)
        except Exception:
            # Diary capture must never interrupt a normal chat or expose its text.
            from astrbot.api import logger

            logger.warning("[Kurumi] 日记对话归档失败，不影响聊天")

    @filter.after_message_sent()
    async def diary_reply_sent(self, event):
        self.capture_diary_chat(event, "user", event.get_message_str())
        result = event.get_result()
        if result:
            text = "\n".join(
                value for part in result.chain
                if isinstance(value := getattr(part, "text", None), str) and value
            )
            self.capture_diary_chat(event, "assistant", text)
