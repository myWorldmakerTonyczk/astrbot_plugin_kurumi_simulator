"""kurumi_set_protection: adjust stop-loss and take-profit lines."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_set_protection"
DESCRIPTION = (
    "为已有持仓设置或修改止损、止盈。达到条件后由程序执行，不等待模型再次判断。"
    "此工具不是价格提醒线；价格事件唤醒还未实现。"
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "position_id": {
            "type": "string",
            "description": "看盘工具返回的持仓id。",
        },
        "reason": {"type": "string", "description": "设置或调整保护线的理由概要。"},
        "stop_loss": {
            "type": "number",
            "description": "止损价；-1保留原设置，0取消止损，正数设置新价格。",
        },
        "take_profit": {
            "type": "number",
            "description": "止盈价；-1保留原设置，0取消止盈，正数设置新价格。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["position_id", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(
        event,
        position_id,
        reason,
        stop_loss=-1,
        take_profit=-1,
        user_id="",
    ):
        return await console(
            plugin,
            event,
            "protect",
            dump(
                dict(
                    position=position_id,
                    reason=reason,
                    sl=stop_loss,
                    tp=take_profit,
                )
            ),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
