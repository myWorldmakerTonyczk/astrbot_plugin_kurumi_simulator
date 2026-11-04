"""kurumi_read_journal: paged unified journal access."""

from ._shared import USER_ID, build_tool, read_logs

NAME = "kurumi_read_journal"
DESCRIPTION = "查询人类、AI及系统的统一交易日志，可用于复盘和了解追加本金。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "pair": {
            "type": "string",
            "description": "可选货币对如EUR/USD；留空查询所有类型，包括追加本金。",
        },
        "before": {
            "type": "integer",
            "description": "分页游标，查询该日志ID之前的记录；0表示最新。",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "返回条数，1到50，默认20。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": [],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, pair="", before=0, limit=20, user_id=""):
        return await read_logs(plugin, event, pair, before, limit, user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
