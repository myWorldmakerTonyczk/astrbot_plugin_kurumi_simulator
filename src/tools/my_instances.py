"""kurumi_my_instances: list instances owned by the caller."""

from ._shared import USER_ID, build_tool, list_instances

NAME = "kurumi_my_instances"
DESCRIPTION = "查找当前用户有权操作的交易实例，不读取其他用户的盘。"
PARAMETERS = {
    "type": "object",
    "properties": {"user_id": {"type": "string", "description": USER_ID}},
    "required": [],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, user_id=""):
        return await list_instances(plugin, event, user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
