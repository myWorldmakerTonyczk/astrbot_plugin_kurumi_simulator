"""Send a scoped review chart directly to the requesting private chat."""

import asyncio

from ..core.engine import dump
from ..core.replay import PERIOD_BY_DAYS, review
from ..core.replay_image import CHARTS, render_png
from ..portal.chat import chat_game, chat_owner
from ._shared import USER_ID, build_tool

NAME = "kurumi_send_review_image"
DESCRIPTION = "用户想看复盘图时，在当前私聊直接发送所选实例的图片。没指定图表时发账户总览；指定单项时选对应 kind。成功发图后简短确认即可。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        kind=dict(type="string", enum=list(CHARTS),
                  description="overview 账户总览（默认，含净值、收益率和回撤）；candles K 线和开平仓标记；equity 净值；return 收益率；drawdown 回撤；activity AI 看盘活动；realized 累计平仓净额；trades 单笔平仓盈亏；fees 手续费"),
        pair=dict(type="string", description="用于 K 线、平仓盈亏或手续费图，例如 EUR/USD。账户总览、净值、收益率和回撤按整个实例计算"),
        days=dict(type="integer", enum=list(PERIOD_BY_DAYS), description="最近 1、7 或 30 天，默认 1 天"),
        end=dict(type="integer", description="可选结束时间，Unix 秒。0 表示当前"),
        user_id=dict(type="string", description=USER_ID),
        instance_id=dict(type="string", description="可选实例 ID 或列表序号"),
    ),
    additionalProperties=False,
)


def build(plugin):
    render_slots = asyncio.Semaphore(2)

    def owner_for(event, user_id):
        return plugin.identity.principal(event, user_id)[0] if user_id else chat_owner(plugin, event)

    async def handler(event, kind="overview", pair="", days=1, end=0, user_id="", instance_id=""):
        from astrbot.api.event import MessageChain
        from astrbot.api.message_components import Image

        try:
            owner = owner_for(event, user_id)
            game = chat_game(plugin, event, owner, instance_id)
            if not isinstance(kind, str) or kind not in CHARTS:
                raise ValueError("图表类型无效。可选：" + "、".join(label[0] for label in CHARTS.values()))
            if kind in {"overview", "equity", "return", "drawdown", "activity"}:
                pair = ""
            if render_slots.locked():
                raise ValueError("图表正在生成，请稍后再试")
            async with render_slots:
                data = await review(
                    plugin, game["id"], pair, days, end, include_candles=kind == "candles",
                )
                png = await asyncio.to_thread(render_png, data, kind)
            if owner_for(event, user_id) != owner or plugin.engine.get(game["id"]).get("owner_id") != owner:
                raise ValueError("实例访问已撤销")
            await event.send(MessageChain(chain=[Image.fromBytes(png)]))
            return dump(dict(ok=True, kind=kind, message=f"已向当前私聊发送「{CHARTS[kind][0]}」。"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))
        except Exception:
            return dump(dict(ok=False, error="图片生成或发送失败，请稍后重试。"))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
