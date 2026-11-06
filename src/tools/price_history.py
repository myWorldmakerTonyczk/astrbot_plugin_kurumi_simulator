"""Scoped, compact read tool."""

from ..core.engine import dump
from ..core.tool_reads import HISTORY_FIELDS
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_price_history"
DESCRIPTION = "查看真实K线区间与最近8根；需要完整序列时传include_bars=true，翻页传next_before。"
PARAMETERS = dict(
    type="object",
    properties=dict(HISTORY_FIELDS, user_id=dict(type="string", description=USER_ID)),
    required=["pair"],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, user_id="", **options):
        return await console(plugin, event, "history", dump(options), user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
