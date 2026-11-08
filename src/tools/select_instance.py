"""kurumi_select_instance: pick the instance used by the current private chat."""

from ._shared import USER_ID, build_tool, select_instance

NAME = "kurumi_select_instance"
DESCRIPTION = "选择当前会话有权限访问的实例；群聊和非绑定私聊须由管理员允许，多个实例时先查询列表。"
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
