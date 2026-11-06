"""Issue panel access only to an independently bound private chat."""

from ..core.engine import dump
from ..portal.chat import chat_game, chat_owner
from ._shared import build_tool

NAME = "kurumi_send_panel"
DESCRIPTION = "用户要远程面板网址或登录入口时调用此工具，默认发送登录入口。明确要本人只读链接时用 read，要可分享复盘时用 summary。直接向已绑定私聊发送。"
PARAMETERS = dict(
    type="object",
    properties=dict(
        mode=dict(type="string", enum=["read", "summary", "login"], description="read 本人只读；summary 可分享的图表摘要；login 账号登录"),
        instance_id=dict(type="string", description="可选，当前用户的实例 ID 或列表序号"),
    ),
    required=[],
    additionalProperties=False,
)


def build(plugin):
    async def handler(event, mode="login", instance_id=""):
        from astrbot.api.event import MessageChain

        try:
            if mode not in ("login", "read", "summary"):
                raise ValueError("面板入口类型无效")
            owner = chat_owner(plugin, event)
            if mode == "login":
                url, username, password = await plugin.portal.account_link(owner)
                try:
                    if chat_owner(plugin, event) != owner:
                        raise ValueError("会话绑定已变化，请重新领取")
                    lines = ["模拟交易登录面板", url]
                    if username:
                        lines.append(f"账号：{username}")
                    if password:
                        lines += [f"首次密码：{password}", "请妥善保管此密码。"]
                    elif username:
                        lines += ["请使用已保存的面板密码。忘记密码可请管理员重置。"]
                    else:
                        lines += ["当前只提供登录网址。已有账号可尝试登录，需要首次凭据时请稍后再领取。"]
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
