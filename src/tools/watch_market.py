"""kurumi_watch_market: read-only account and market snapshot."""

from ._shared import USER_ID, build_tool, console

NAME = "kurumi_watch_market"
DESCRIPTION = (
    "查看绑定游戏的真实报价、账户、持仓、费用、交易规则、持仓计划与近期日志。"
    "操作前先查盘；market_error 或报价过期时不能假装已经成交。资金全部为虚拟。"
)
PARAMETERS = {
    "type": "object",
    "properties": {"user_id": {"type": "string", "description": USER_ID}},
    "required": [],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, user_id=""):
        return await console(plugin, event, "state", "{}", user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
