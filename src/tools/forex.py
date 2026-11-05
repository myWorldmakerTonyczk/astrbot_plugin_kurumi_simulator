"""kurumi_forex: generic console-compatible entry point."""

from ._shared import USER_ID, build_tool, console

NAME = "kurumi_forex"
DESCRIPTION = "在绑定的外汇账户查盘、交易或读取长期交易日志。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "state查账户及行情，logs查日志，open开仓，close平仓，observe观望，plan更新计划，计划使用kurumi_write_plan，笔记暂不修改。",
        },
        "parameters": {
            "type": "string",
            "description": "JSON对象。操作必须含reason理由，用户无额外要求时按原人设口吻；open含pair如EUR/USD、side为buy或sell、units基础货币数量，可填sl/tp价格；close含position持仓ID；plan/notes含text；logs可填before日志ID。先state查询规则和有效报价，未成功不得声称成交。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, action, parameters="{}", user_id=""):
        return await console(plugin, event, action, parameters, user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
