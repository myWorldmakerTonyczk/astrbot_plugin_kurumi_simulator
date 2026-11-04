"""Agent may change only its selected instance's administrator-authorized preferences."""

from ..core.engine import dump
from ..users.policy import change_notices
from ..notifications.settings import DEFAULTS
from ._shared import USER_ID, build_tool, bound_game

NAME = "kurumi_set_notifications"
DESCRIPTION = "按用户意愿修改当前实例的主动外汇汇报；须管理员允许。所有主动消息（含爆仓和保证金）受免打扰黑名单约束，默认00:00～07:00不发送。分析汇报可在允许时段内随机延迟。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        settings=dict(
            type="object",
            properties={
                key: dict(type="boolean" if isinstance(value, bool) else "string")
                for key, value in DEFAULTS.items()
            },
            additionalProperties=False,
            description="部分更新：enabled总开关，analysis看盘汇报，liquidation强平，margin_call保证金，deposit追加资金，end结束；use_window限时段，random_delay随机延迟；window_start/end和quiet_start/end为HH:MM，timezone时区",
        ),
        user_id=dict(type="string", description=USER_ID),
    ),
    required=["settings"],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, settings, user_id=""):
        try:
            game = bound_game(plugin, event, user_id)
            return dump(change_notices(plugin, game["id"], settings, "ai"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
