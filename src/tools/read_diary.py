"""Read the selected instance's private diary through the same identity gate."""

from ..core.engine import dump
from ._shared import USER_ID, build_tool, bound_game

NAME = "kurumi_read_diary"
DESCRIPTION = "只读查询当前用户所选交易实例的历史日记/经验，日记含交易复盘与真实互动。不能读取其他用户实例。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        before=dict(
            type="string", description="可选，查询此日期YYYY-MM-DD以前的日记；空为最新"
        ),
        limit=dict(type="integer", minimum=1, maximum=10),
        user_id=dict(type="string", description=USER_ID),
    ),
    required=[],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, before="", limit=3, user_id=""):
        try:
            game = bound_game(plugin, event, user_id)
            if type(limit) is not int or not 1 <= limit <= 10:
                raise ValueError("条数须在1～10之间")
            entries = plugin.diary.store.list(game["id"], before, limit)
            return dump(
                dict(
                    ok=True,
                    entries=[row for row in entries if row["status"] == "success"],
                )
            )
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
