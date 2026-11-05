"""Central registry that installs every chat-facing kurumi tool."""

from . import (
    close_position,
    forex,
    my_instances,
    open_position,
    price_history,
    read_journal,
    read_diary,
    send_review_image,
    select_instance,
    set_protection,
    set_notifications,
    virtual_loan,
    watch_market,
    write_memory,
    write_plan,
)

TOOL_MODULES = (
    forex,
    watch_market,
    read_journal,
    read_diary,
    open_position,
    close_position,
    set_protection,
    set_notifications,
    write_memory,
    virtual_loan,
    my_instances,
    select_instance,
    write_plan,
    price_history,
    send_review_image,
)


def build_tools(plugin):
    return [module.build(plugin) for module in TOOL_MODULES]


def register_tools(plugin):
    tools = build_tools(plugin)
    plugin.context.add_llm_tools(*tools)
    return tools
