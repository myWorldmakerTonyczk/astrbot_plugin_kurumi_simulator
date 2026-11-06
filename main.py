"""AstrBot discovered entry point."""

from astrbot.api.event import filter
from astrbot.api.star import Star

from .src.integration.plugin import KurumiMixin
from .src.tools.registry import register_tools


class KurumiSimulator(KurumiMixin, Star):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        register_tools(self)

    async def terminate(self):
        # AstrBot checks the entry class dictionary before invoking this hook.
        await super().terminate()

    @filter.on_llm_request()
    async def trading_context(self, event, request):
        self.capture_diary_chat(event, "user", event.get_message_str())

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
