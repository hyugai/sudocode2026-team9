from telesale_agent.core.interfaces import Observer
from telesale_agent.core.models import ActionStatus, Observation, TurnContext

class BasicObserver(Observer):
    """Local demo that logs the result of the previous action."""

    async def observe(self, context: TurnContext) -> Observation:
        if context.action_result is None:
            raise ValueError("action result is required before observing")

        match context.action_result.status:
            case ActionStatus.EXECUTED:
                summary = "Action completed successfully."
                # If we called an API, we want to continue so we can talk to the user.
                # If we just responded to the user, we should stop.
                should_continue = context.plan.action == "call_api"
            case ActionStatus.BLOCKED:
                summary = "Action blocked by policy guardrails."
                should_continue = True
            case ActionStatus.FAILED:
                summary = f"Action failed: {context.action_result.error}"
                should_continue = True
            case _:
                summary = "Unknown status."
                should_continue = False

        return Observation(summary=summary, should_continue=should_continue)
