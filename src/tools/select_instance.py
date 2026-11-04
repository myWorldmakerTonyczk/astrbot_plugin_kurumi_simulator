"""kurumi_select_instance: pick the instance used by the current private chat."""

from ._shared import USER_ID, build_tool, select_instance

NAME = "kurumi_select_instance"
DESCRIPTION = "选择当前私聊要操作的实例，同一用户多个盘时先选择，不能选择他人的盘。"
PARAMETERS = {
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "string",
            "description": "实例列表返回的完整ID或从1开始的序号。",
        },
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["instance_id"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, instance_id, user_id=""):
        return await select_instance(plugin, event, instance_id, user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
