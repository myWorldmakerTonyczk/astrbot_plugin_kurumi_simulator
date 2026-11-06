"""kurumi_read_journal: paged unified journal access."""

from ..core.engine import dump
from ..core.journal import JOURNAL_FIELDS
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_read_journal"
DESCRIPTION = "按页读取交易日志，可筛选实际操作。查看完整计划或复盘时才开启 include_text。"
PARAMETERS = dict(
    type="object",
    properties=dict(JOURNAL_FIELDS, user_id=dict(type="string", description=USER_ID)),
    required=[],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, user_id="", **options):
        return await console(plugin, event, "logs", dump(options), user_id)

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
