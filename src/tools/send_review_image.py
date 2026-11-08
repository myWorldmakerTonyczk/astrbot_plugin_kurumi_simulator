"""Send a scoped review chart directly to the requesting private chat."""

import asyncio

from ..core.engine import dump
from ..core.replay import PERIOD_BY_DAYS, review
from ..core.replay_image import CHARTS, render_chart_sheet
from ..portal.chat import chat_game, chat_owner
from ._shared import USER_ID, build_tool
from ..users.tool_access import selected_in_call, permitted

NAME = "kurumi_send_review_image"
DESCRIPTION = "用户想看复盘图时，在当前会话直接发送所选实例的图片。没指定图表时发账户总览；指定单项时用 kind；diary 发日记图片，text 将提供的文字排成图片，多项时用 kinds 按顺序拼成一张图。成功发图后简短确认即可。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        kind=dict(type="string", enum=list(CHARTS),
                  description="overview 账户总览（默认，含净值、收益率和回撤）；candles K 线和开平仓标记；equity 净值；return 收益率；drawdown 回撤；activity AI 看盘活动；realized 累计平仓净额；trades 单笔平仓盈亏；fees 手续费；diary 日记图片；text 文字图片"),
        kinds=dict(type="array", items=dict(type="string", enum=list(CHARTS)),
                   minItems=1, maxItems=len(CHARTS),
                   description="多个图表类型，按数组顺序拼成一张图；传入时优先使用此参数"),
        diary_date=dict(type="string", description="日记日期 YYYY-MM-DD，留空取最近一篇"),
        text=dict(type="string", maxLength=6000, description="kind=text 时要发送的正文，1～6000字"),
        pair=dict(type="string", description="用于 K 线、平仓盈亏或手续费图，例如 EUR/USD。账户总览、净值、收益率和回撤按整个实例计算"),
        days=dict(type="integer", enum=list(PERIOD_BY_DAYS), description="最近 1、7 或 30 天，默认 1 天"),
        end=dict(type="integer", description="可选结束时间，Unix 秒。0 表示当前"),
        user_id=dict(type="string", description=USER_ID),
        instance_id=dict(type="string", description="可选实例 ID 或列表序号"),
    ),
    required=[],
    additionalProperties=False,
)


def build(plugin):
    render_slots = asyncio.Semaphore(2)

    def owner_for(event, user_id):
        active = selected_in_call(plugin)
        if active:
            return active.get("owner_id")
        return plugin.identity.principal(event, user_id)[0] if user_id else chat_owner(plugin, event)

    async def handler(event, kind="overview", pair="", days=1, end=0, user_id="", instance_id="", kinds=None, diary_date="", text=""):
        from astrbot.api.event import MessageChain
        from astrbot.api.message_components import Image

        try:
            owner = owner_for(event, user_id)
            game = selected_in_call(plugin) or chat_game(plugin, event, owner, instance_id)
            selected = [kind] if kinds is None else kinds
            if (not isinstance(selected, list) or not 1 <= len(selected) <= len(CHARTS)
                    or any(not isinstance(item, str) or item not in CHARTS for item in selected)):
                raise ValueError("图表类型无效。可选：" + "、".join(label[0] for label in CHARTS.values()))
            selected = list(dict.fromkeys(selected))
            if not any(item in {"candles", "realized", "trades", "fees"} for item in selected):
                pair = ""
            if render_slots.locked():
                raise ValueError("图表正在生成，请稍后再试")
            async with render_slots:
                data = await review(
                    plugin, game["id"], pair, days, end, include_candles="candles" in selected,
                )
                data["text_panels"] = {}
                if "diary" in selected:
                    from datetime import date, timedelta
                    before = ""
                    if diary_date:
                        before = (date.fromisoformat(diary_date) + timedelta(days=1)).isoformat()
                    rows = plugin.diary.store.list(game["id"], before, 1, successful_only=True)
                    if not rows or (diary_date and rows[0]["day"] != diary_date):
                        raise ValueError("这个日期没有已写好的日记" if diary_date else "还没有已写好的日记")
                    data["text_panels"]["diary"] = dict(title="交易日记", subtitle=rows[0]["day"], content=rows[0]["content"][:6000] + ("\n……日记较长，其余内容请查询日记工具" if len(rows[0]["content"]) > 6000 else ""))
                if "text" in selected:
                    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 6000:
                        raise ValueError("图片正文须为 1～6000 字")
                    data["text_panels"]["text"] = dict(title="文字记录", subtitle="", content=text.strip())
                png = await asyncio.to_thread(render_chart_sheet, data, selected)
            if not permitted(plugin, event, plugin.engine.get(game["id"]), True) or plugin.engine.get(game["id"])["status"] == "paused":
                raise ValueError("实例访问已撤销")
            await event.send(MessageChain(chain=[Image.fromBytes(png)]))
            if len(selected) == 1:
                kind = selected[0]
                return dump(dict(ok=True, kind=kind, message=f"已向当前会话发送「{CHARTS[kind][0]}」。"))
            return dump(dict(ok=True, kinds=selected, message="已向当前会话发送一张复盘拼图。"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))
        except Exception:
            return dump(dict(ok=False, error="图片生成或发送失败，请稍后重试。"))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
