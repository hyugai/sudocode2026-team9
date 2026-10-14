from telesale_agent.core.interfaces import CallBriefBuilder
from telesale_agent.core.models import CallBrief, TurnContext

class LLMCallBriefBuilder(CallBriefBuilder):
    """Build a compact call brief deterministically from CRM and memory."""

    def __init__(self, model_name: str | None = None):
        # Keep the argument for callers written against the old API. Call brief
        # construction is intentionally local so it cannot add an extra model
        # request per turn.
        self.model_name = model_name

    async def build_call_brief(self, context: TurnContext) -> CallBrief:
        if context.identity is None:
            raise ValueError("identity is required")

        crm_profile = context.state.customer_profile or {}
        memory = context.state.customer_memory or {}
        history = context.state.past_history or {}
        customer_name = crm_profile.get("name") or context.identity.profile.get("name")
        past_sessions = memory.get("episodes", [])
        raw_facts = memory.get("facts", {})
        if not isinstance(raw_facts, dict):
            raw_facts = {}
        canonical_facts = {
            key: value
            for key, value in raw_facts.items()
            if value not in (None, "", [])
        }
        remembered_preferences = {
            "profile": memory.get("profile", ""),
            "behaviors": memory.get("behaviors", ""),
            "facts": canonical_facts,
            "atomic_facts": memory.get("atomic_facts", []),
            "foresights": memory.get("foresights", []),
        }
        current_turn = {
            "intent": context.perception.intent if context.perception else "unknown",
            "intents": context.perception.intents if context.perception else [],
            "entities": context.perception.entities if context.perception else {},
            "new_facts": context.state.memory_deltas,
        }
        historical_context = {
            "remembered_preferences": remembered_preferences,
            "episodes": past_sessions,
            "past_orders": history.get("past_orders", []),
            "current_turn": current_turn,
        }
        active_promotions = (
            context.retrieved.active_promotions if context.retrieved else []
        )
        
        has_history = bool(
            past_sessions
            or history.get("past_orders")
            or memory.get("profile")
            or memory.get("behaviors")
            or memory.get("facts")
            or memory.get("atomic_facts")
            or memory.get("foresights")
        )
        if not has_history:
            current_intent = current_turn["intent"]
            return CallBrief(
                customer_id=context.identity.customer_id,
                customer_name=str(customer_name) if customer_name else None,
                summary=f"New customer context. Current intent: {current_intent}.",
                needs=[f"Current intent: {current_intent}"],
                active_promotions=active_promotions,
                verified_customer_data=crm_profile,
                remembered_preferences=remembered_preferences,
                relevant_episodes=past_sessions,
            )

        facts = remembered_preferences.get("facts") or {}
        extracted_needs = [
            f"{key}: {value}" for key, value in list(facts.items())[-8:]
        ]

        ep_summaries = []
        for ep in past_sessions:
            if not isinstance(ep, dict):
                continue
            episode_text = ep.get("summary") or ep.get("content")
            if episode_text:
                compact = " ".join(str(episode_text).split())
                ep_summaries.append(compact[-600:])

        if ep_summaries:
            summary = " | ".join(ep_summaries[-2:])
        elif extracted_needs:
            summary = f"Customer facts: {', '.join(extracted_needs[:3])}"
        else:
            summary = "Returning customer."

        needs = extracted_needs

        return CallBrief(
            customer_id=context.identity.customer_id,
            customer_name=str(customer_name) if customer_name else None,
            summary=summary,
            needs=needs,
            active_promotions=active_promotions,
            verified_customer_data=crm_profile,
            remembered_preferences=remembered_preferences,
            relevant_episodes=past_sessions,
        )
