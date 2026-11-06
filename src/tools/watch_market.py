"""kurumi_watch_market: read-only account and market snapshot."""

from ..core.journal import LOG_LIMIT
from ..core.tool_reads import MARKET_DETAIL
from ..core.engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_watch_market"
DESCRIPTION = (
    "查看绑定游戏的真实报价、账户、持仓、费用、交易规则、持仓计划与近期日志。"
    "完整计划按需传include_details=true；操作前先查盘；market_error 或报价过期时不能假装已经成交。"
)
PARAMETERS = {
    "type": "object",
    "properties": {"log_limit": LOG_LIMIT, "include_details": MARKET_DETAIL, "user_id": {"type": "string", "description": USER_ID}},
    "required": [],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, user_id="", log_limit=30, include_details=False):
        return await console(plugin, event, "state", dump(dict(log_limit=log_limit, include_details=include_details)), user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
