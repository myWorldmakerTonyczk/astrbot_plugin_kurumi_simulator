"""Issue panel access only to an independently bound private chat."""

from ..core.engine import dump
from ._shared import build_tool

NAME = "kurumi_send_panel"
DESCRIPTION = "用户明确要面板时，向真实绑定的当前私聊发送只读链接。可领取自己的面板或生成不含私密文本的摘要分享。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        mode=dict(type="string", enum=["read", "summary"], description="read 本人只读；summary 可分享的图表摘要"),
        instance_id=dict(type="string", description="可选，当前用户的实例 ID 或列表序号"),
    ),
    required=["mode"],
    additionalProperties=False,
)


def bound_owner(plugin, event):
    if getattr(event.platform_meta, "name", "") == "kurumi_silent":
        raise ValueError("仅可在已绑定的私聊领取面板")
    try:
        return plugin.identity.principal(event)[0]
    except ValueError:
        raise ValueError("请在管理员已绑定的 QQ 或 UMO 私聊领取面板") from None


def build(plugin):
    async def handler(event, mode, instance_id=""):
        from astrbot.api.event import MessageChain

        try:
            owner = bound_owner(plugin, event)
            game = (
                plugin.identity.select(event, instance_id) if instance_id
                else plugin.identity.selected(event)
            )
            url = plugin.portal.link(owner, game["id"], mode)
            title = "本人只读面板" if mode == "read" else "可转发的复盘摘要"
            await event.send(MessageChain().message(f"{title}\n{url}\n链接 5 分钟内可兑换一次。"))
            return dump(dict(ok=True, message="已向当前私聊发送面板入口。"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))
        except Exception:
            return dump(dict(ok=False, error="发送面板入口失败，请重试。"))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
