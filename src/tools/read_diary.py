"""Scoped, compact read tool."""

from ..core.engine import dump
from ..core.tool_reads import DIARY_FIELDS
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_read_diary"
DESCRIPTION = "读取当前实例日记摘要；需要完整正文时传include_text=true，可按next_before翻页。"
PARAMETERS = dict(
    type="object",
    properties=dict(DIARY_FIELDS, user_id=dict(type="string", description=USER_ID)),
    required=[],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, user_id="", **options):
        return await console(plugin, event, "diary", dump(options), user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
