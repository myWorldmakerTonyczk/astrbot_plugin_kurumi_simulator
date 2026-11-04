"""kurumi_write_memory: compatibility entry that still only writes plans."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_write_memory"
DESCRIPTION = "兼容入口，仅保存交易计划，操作会记入交易日志。不能改写成交事实。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "仅plan，笔记暂不扩展。",
        },
        "text": {
            "type": "string",
            "description": "新的完整计划或经验，最多6000字符；保留仍有价值的已有内容。",
        },
        "reason": {"type": "string", "description": "本次更新的简短说明。"},
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["kind", "text", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, kind, text, reason, user_id=""):
        if kind != "plan":
            return "未执行：笔记暂不扩展，计划请使用kurumi_write_plan。"
        return await console(
            plugin,
            event,
            "plan",
            dump(dict(text=text, reason=reason)),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
