from telesale_agent.core.interfaces import Actor
from telesale_agent.core.models import ActionResult, ActionStatus, TurnContext
from telesale_agent.tools.registry import dispatch_tool


class LocalActor(Actor):
    """
    Executes the action planned by the LLM.

    - For tool-based actions (catalog.search, order.create, etc.):
      calls dispatch_tool() with the BTC-standard tool name.
    - For non-tool actions (respond_to_customer, transfer_to_human):
      returns EXECUTED directly so the response text flows through.
    """

    _NON_TOOL_ACTIONS = {
        "respond_to_customer",
        "clarify",
        "acknowledge",
        "end_call",
        "transfer_to_human",
    }

    async def act(self, context: TurnContext) -> ActionResult:
        if context.plan is None:
            raise ValueError("action plan is required")

        action = context.plan.action
        tool_name = context.plan.tool_name
        args = context.plan.arguments or {}

        # --- Non-tool actions: just pass through ---
        if action in self._NON_TOOL_ACTIONS and not tool_name:
            return ActionResult(status=ActionStatus.EXECUTED, output={})

        # --- Tool-based actions: use BTC-standard tool name ---
        effective_tool = tool_name or action  # LLM may put tool name in action or tool_name

        if effective_tool == "order.create":
            if "customer_phone" not in args and context.identity and context.identity.customer_id:
                args["customer_phone"] = context.identity.customer_id
            if "qty" not in args:
                args["qty"] = 1

        result = dispatch_tool(effective_tool, args)

        if "error" in result:
            return ActionResult(
                status=ActionStatus.FAILED,
                output=result,
                error=result["error"],
            )

        return ActionResult(status=ActionStatus.EXECUTED, output=result)
