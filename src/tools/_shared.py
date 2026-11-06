"""Shared resolution and execution helpers for chat-facing tools."""

import json

from ..core.engine import dump
from ..core.trading import execute

USER_ID = "随机ID方式每次调用必填管理员提供的完整ID；QQ/UMO绑定可留空。不得猜测或回显ID。"


def build_tool(name, description, parameters, handler):
    """Create an AstrBot FunctionTool tied to the module that defines it.

    AstrBot derives plugin ownership from ``tool.__module__``. The handler is
    defined in a tool module, so subclassing with that module keeps the tool
    attached to this plugin instead of ``astrbot.core.agent.tool``.
    """
    from astrbot.core.agent.tool import FunctionTool

    tool_cls = type("KurumiTool", (FunctionTool,), {"__module__": handler.__module__})
    return tool_cls(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
    )


def bound_game(plugin, event, user_id=""):
    return plugin.identity.selected(event, user_id)


async def list_instances(plugin, event, user_id=""):
    try:
        games = plugin.identity.instances(event, user_id)
        return dump(
            dict(
                ok=True,
                instances=[
                    dict(id=g["id"], name=g["name"], status=g["status"]) for g in games
                ],
                message="只有一个实例时可直接查询；多个实例请先选择。",
            )
        )
    except (ValueError, TypeError) as exc:
        return dump(dict(ok=False, error=str(exc)))


async def select_instance(plugin, event, instance_id, user_id=""):
    try:
        game = plugin.identity.select(event, instance_id, user_id)
        return dump(dict(ok=True, instance=dict(id=game["id"], name=game["name"])))
    except (ValueError, TypeError) as exc:
        return dump(dict(ok=False, error=str(exc)))


async def console(plugin, event, action, parameters, user_id=""):
    try:
        game = bound_game(plugin, event, user_id)
        body = json.loads(parameters)
        if not isinstance(body, dict):
            raise ValueError("参数须为JSON对象")
        result = await execute(plugin, game["id"], action, body)
        return dump(dict(ok=True, result=result))
    except (ValueError, TypeError) as exc:
        return dump(dict(ok=False, error=str(exc)))
