"""Chat tool entry points: bearer IDs never become trading context."""

import json
from .engine import dump
from .trading import execute


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


async def read_logs(plugin, event, pair="", before=0, limit=20, user_id=""):
    return await console(
        plugin,
        event,
        "logs",
        dump(dict(pair=pair, before=before, limit=limit)),
        user_id,
    )


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
