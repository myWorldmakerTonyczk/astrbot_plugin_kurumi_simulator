"""Independent scope permissions and instance isolation for chat tools."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.core.engine import Engine
from src.users.identity import Identity
from src.users import policy
from src.users.tool_access import CURRENT, available, permitted, resolve, is_read
from src.tools._shared import bound_game
from src.tools.registry import build_tools


def event(kind="FriendMessage", sender="1"):
    return SimpleNamespace(unified_msg_origin=f"bot:{kind}:{sender}", get_sender_id=lambda: sender)


class ToolAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine(":memory:")
        self.addCleanup(self.engine.db.close)
        self.plugin = SimpleNamespace(engine=self.engine, identity=Identity(self.engine))
        self.first = self.engine.create({"user_binding":{"type":"umo","values":["bot:FriendMessage:1"]}})
        self.second = self.engine.create({"user_binding":{"type":"umo","values":["bot:FriendMessage:2"]}})

    def grant(self, game, **values):
        uid = game["owner_id"]
        data = policy.validate({**policy.for_user(self.engine.db, uid), **values})
        self.engine.db.execute("INSERT OR REPLACE INTO sim_user_policy VALUES(?,?)", (uid,json.dumps(data)))

    def test_default_closed_and_own_private_open(self):
        for read in (True,False):
            self.assertTrue(permitted(self.plugin,event(),self.first,read))
            self.assertFalse(permitted(self.plugin,event(sender="2"),self.first,read))
            self.assertFalse(permitted(self.plugin,event("GroupMessage"),self.first,read))
        self.assertEqual([g["id"] for g in available(self.plugin,event(),True)],[self.first["id"]])

    def test_four_switches_independent_and_target_owner_scoped(self):
        for scope in ("group","foreign"):
            incoming = event("GroupMessage") if scope=="group" else event(sender="2")
            for read in (True,False):
                key = f"allow_{scope}_{'read' if read else 'trade'}"
                self.grant(self.first, **({k:False for k in policy.DEFAULTS if k.startswith(("allow_group_","allow_foreign_"))} | {key:True}))
                self.assertTrue(permitted(self.plugin,incoming,self.first,read))
                self.assertFalse(permitted(self.plugin,incoming,self.first,not read))
                self.assertFalse(permitted(self.plugin,event("GroupMessage", "9"),self.second,read))

    def test_selection_revocation_and_context_reset(self):
        incoming = event("GroupMessage")
        self.grant(self.first,allow_group_read=True)
        self.assertEqual(resolve(self.plugin,incoming,True,self.first["id"])["id"],self.first["id"])
        token = CURRENT.set(self.first["id"])
        try:
            self.assertEqual(bound_game(self.plugin,incoming)["id"],self.first["id"])
        finally:
            CURRENT.reset(token)
        self.grant(self.first,allow_group_read=False)
        with self.assertRaises(ValueError): resolve(self.plugin,incoming,True,self.first["id"])

    def test_generic_console_does_not_bypass_trade_permission(self):
        self.assertTrue(is_read("kurumi_forex",{"action":"logs"}))
        self.assertFalse(is_read("kurumi_forex",{"action":"open"}))
        self.assertFalse(is_read("kurumi_write_plan",{}))

    async def test_registered_tools_deny_writes_and_keep_explicit_target(self):
        import sys, types
        module=types.ModuleType("astrbot.core.agent.tool")
        module.FunctionTool=type("FunctionTool",(),{"__init__":lambda self,**kw:self.__dict__.update(kw)})
        with patch.dict(sys.modules,{"astrbot.core.agent.tool":module}):
            tools={t.name:t for t in build_tools(self.plugin)}
        incoming=event("GroupMessage")
        self.grant(self.first,allow_group_read=True)
        with patch("src.tools._shared.execute", return_value={"target":self.first["id"]}) as execute:
            result=json.loads(await tools["kurumi_forex"].handler(incoming,action="state",instance_id=self.first["id"]))
            self.assertTrue(result["ok"])
            self.assertEqual(execute.call_args.args[1],self.first["id"])
            result=json.loads(await tools["kurumi_forex"].handler(incoming,action="open",parameters="{}",instance_id=self.first["id"]))
            self.assertFalse(result["ok"])
            self.assertEqual(execute.call_count,1)
        self.assertIsNone(CURRENT.get())
        self.grant(self.first,allow_group_read=False,allow_group_trade=True)
        result=json.loads(await tools["kurumi_my_instances"].handler(incoming))
        self.assertEqual(len(result["instances"]),1)
        result=json.loads(await tools["kurumi_select_instance"].handler(incoming,instance_id=self.first["id"]))
        self.assertTrue(result["ok"])
