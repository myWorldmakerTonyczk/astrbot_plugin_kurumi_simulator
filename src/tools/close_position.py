"""kurumi_close_position: settle one virtual position."""

from ..engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_close_position"
DESCRIPTION = "平掉指定虚拟持仓，结算盈亏与手续费，并记录理由。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "position_id": {
            "type": "string",
            "description": "看盘工具返回的持仓id，不能填写货币对代替。",
        },
        "reason": {"type": "string", "description": "本次平仓的简短理由。"},
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["position_id", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, position_id, reason, user_id=""):
        return await console(
            plugin,
            event,
            "close",
            dump(dict(position=position_id, reason=reason)),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
