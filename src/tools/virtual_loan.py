"""kurumi_virtual_loan: borrow or repay within the human-set limit."""

from ..engine import dump
from ._shared import USER_ID, build_tool, console

NAME = "kurumi_virtual_loan"
DESCRIPTION = (
    "在由人类启用的本局虚拟贷款额度内借款或还款。借入不算收益，债务和利息抵减净值。"
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["borrow", "repay"],
            "description": "borrow借款，repay还款；不能自行启用贷款或提高额度。",
        },
        "amount": {
            "type": "number",
            "description": "虚拟美元金额，必须大于零；还款先偿利息。",
        },
        "reason": {"type": "string", "description": "本次借还款的理由概要。"},
        "user_id": {"type": "string", "description": USER_ID},
    },
    "required": ["action", "amount", "reason"],
    "additionalProperties": False,
}


def build(plugin):
    async def handler(event, action, amount, reason, user_id=""):
        if action not in ("borrow", "repay"):
            return "未执行：只允许borrow或repay。"
        return await console(
            plugin,
            event,
            action,
            dump(dict(amount=amount, reason=reason)),
            user_id,
        )

    return build_tool(NAME, DESCRIPTION, PARAMETERS, handler)
