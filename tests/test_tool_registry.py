import unittest

from src.tools.registry import TOOL_MODULES

EXPECTED_TOOLS = [
    "kurumi_forex",
    "kurumi_watch_market",
    "kurumi_read_journal",
    "kurumi_read_diary",
    "kurumi_open_position",
    "kurumi_close_position",
    "kurumi_set_protection",
    "kurumi_set_notifications",
    "kurumi_write_memory",
    "kurumi_virtual_loan",
    "kurumi_my_instances",
    "kurumi_select_instance",
    "kurumi_write_plan",
    "kurumi_price_history",
    "kurumi_send_review_image",
    "kurumi_send_panel",
]


class ToolRegistryTests(unittest.TestCase):
    def test_one_module_per_tool_without_duplicates(self):
        names = [module.NAME for module in TOOL_MODULES]
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(len(names), len(set(names)))

    def test_schemas_are_well_formed(self):
        for module in TOOL_MODULES:
            with self.subTest(tool=module.NAME):
                self.assertTrue(module.DESCRIPTION)
                self.assertEqual(module.PARAMETERS["type"], "object")
                self.assertIs(module.PARAMETERS["additionalProperties"], False)
                properties = set(module.PARAMETERS["properties"])
                self.assertTrue(set(module.PARAMETERS["required"]) <= properties)
                self.assertTrue(callable(module.build))
