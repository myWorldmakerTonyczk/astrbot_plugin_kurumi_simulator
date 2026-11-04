"""kurumi_write_plan: persist the current trading plan."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_write_plan"
DESCRIPTION = (
    "随时保存当前实例的完整交易计划，跨聊天和后台看盘保留，并记录修改理由。"
    "先读取旧计划，保留有效内容；不修改笔记。"
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "完整计划，1～6000字。"},
        "reason": {"type": "string", "description": "这次调整计划的简短理由概要。"},
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["text", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, text, reason, user_id=""):
        return await console(
            plugin,
            event,
            "plan",
            dump(dict(text=text, reason=reason)),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
