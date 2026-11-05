"""kurumi_open_position: open a virtual position with optional protections."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_open_position"
DESCRIPTION = (
    "开立外汇持仓。同一货币对支持多笔独立持仓；反向开仓是新增仓位，不自动平旧仓。"
    "成功及拒绝均记日志。"
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "pair": {
            "type": "string",
            "description": "允许的货币对，如EUR/USD，先调用看盘工具确认。",
        },
        "side": {
            "type": "string",
            "enum": ["buy", "sell"],
            "description": "buy表示看涨，sell表示看跌。",
        },
        "units": {
            "type": "number",
            "description": "基础货币数量，不是手数，必须大于零。",
        },
        "reason": {"type": "string", "description": "必填简短决策理由，默认用原人设的语气。"},
        "stop_loss": {
            "type": "number",
            "description": "可选止损价格，0表示不设。",
        },
        "take_profit": {
            "type": "number",
            "description": "可选止盈价格，0表示不设。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["pair", "side", "units", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(
        event,
        pair,
        side,
        units,
        reason,
        stop_loss=0,
        take_profit=0,
        user_id="",
    ):
        return await console(
            plugin,
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

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
