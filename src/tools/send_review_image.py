"""Send a scoped review chart directly to the requesting private chat."""

import asyncio

from ..core.engine import dump
from ..core.replay import PERIOD_BY_DAYS, review
from ..core.replay_image import CHARTS, render_png
from ._shared import USER_ID, bound_game, build_tool

NAME = "kurumi_send_review_image"
DESCRIPTION = "用户想看复盘图时，在当前私聊直接发送所选实例的图片。工具已发图后只需简短确认。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        kind=dict(type="string", enum=list(CHARTS),
                  description="candles K线成交；equity 净值；return 收益率；drawdown 回撤；activity 看盘活动；realized 累计平仓净额；trades 单笔平仓；fees 手续费"),
        pair=dict(type="string", description="可选实例内货币对，例如 EUR/USD"),
        days=dict(type="integer", enum=list(PERIOD_BY_DAYS), description="最近 1、7 或 30 天"),
        end=dict(type="integer", description="可选结束时间，Unix 秒。0 表示当前"),
        user_id=dict(type="string", description=USER_ID),
    ),
    required=["kind"],
    additionalProperties=False,
)


def build(plugin):
    render_slots = asyncio.Semaphore(2)

    async def handler(event, kind, pair="", days=1, end=0, user_id=""):
        from astrbot.api.event import MessageChain
        from astrbot.api.message_components import Image

        try:
            game = bound_game(plugin, event, user_id)
            if kind not in CHARTS:
                raise ValueError("图表类型无效")
            if render_slots.locked():
                raise ValueError("图表正在生成，请稍后再试")
            async with render_slots:
                data = await review(
                    plugin, game["id"], pair, days, end, include_candles=kind == "candles",
                )
                png = await asyncio.to_thread(render_png, data, kind)
            if plugin.identity.principal(event, user_id)[0] != plugin.engine.get(game["id"]).get("owner_id"):
                raise ValueError("实例访问已撤销")
            await event.send(MessageChain(chain=[Image.fromBytes(png)]))
            return dump(dict(ok=True, message="已将图片发到当前私聊。"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))
        except Exception:
            return dump(dict(ok=False, error="图片生成或发送失败，请稍后重试。"))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
