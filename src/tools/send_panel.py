"""Issue panel access only to an independently bound private chat."""

from ..core.engine import dump
from ..portal.chat import chat_game, chat_owner
from ._shared import build_tool

NAME = "kurumi_send_panel"
DESCRIPTION = "用户明确要面板时，向真实绑定的当前私聊发送只读链接、可分享摘要，或账号登录入口和首次凭据。账号密码不返回给模型。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        mode=dict(type="string", enum=["read", "summary", "login"], description="read 本人只读；summary 可分享的图表摘要；login 账号登录"),
        instance_id=dict(type="string", description="可选，当前用户的实例 ID 或列表序号"),
    ),
    required=["mode"],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, mode, instance_id=""):
        from astrbot.api.event import MessageChain

        try:
            owner = chat_owner(plugin, event)
            if mode == "login":
                url, username, password = await plugin.portal.account_link(owner)
                try:
                    if chat_owner(plugin, event) != owner:
                        raise ValueError("会话绑定已变化，请重新领取")
                    lines = ["模拟交易登录面板", url, f"账号：{username}"]
                    if password:
                        lines += [f"首次密码：{password}", "请妥善保管此密码。"]
                    else:
                        lines += ["请使用首次领取时的密码。忘记密码可请管理员重置。"]
                    await event.send(MessageChain().message("\n".join(lines)))
                except Exception:
                    # The first password is unrecoverable if the adapter rejects the send.
                    if password and plugin.portal.accounts.username(owner) == username:
                        plugin.portal.accounts.reset(owner)
                    raise
                return dump(dict(ok=True, message="已向当前私聊发送登录入口。"))
            game = chat_game(plugin, event, owner, instance_id)
            url = plugin.portal.link(owner, game["id"], mode)
            title = "本人只读面板" if mode == "read" else "可转发的复盘摘要"
            await event.send(MessageChain().message(f"{title}\n{url}\n链接 5 分钟内可兑换一次。"))
            return dump(dict(ok=True, message="已向当前私聊发送面板入口。"))
        except (ValueError, TypeError) as exc:
            return dump(dict(ok=False, error=str(exc)))
        except Exception:
            return dump(dict(ok=False, error="发送面板入口失败，请重试。"))

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
