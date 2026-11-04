"""kurumi_price_history: read-only OHLC history for decision support."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_price_history"
DESCRIPTION = "读取真实历史K线辅助判断，不会下单。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "pair": {"type": "string", "description": "货币对，例如EUR/USD。"},
        "period": {
            "type": "string",
            "enum": ["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"],
            "description": "1m、5m、15m、1h、4h、1d、1w、1M。",
        },
        "limit": {
            "type": "integer",
            "minimum": 10,
            "maximum": 200,
            "description": "10～200条，默认80。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["pair"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, pair, period="1h", limit=80, user_id=""):
        return await console(
            plugin,
            event,
            "history",
            dump(dict(pair=pair, period=period, limit=limit)),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
