from datetime import date, datetime, timezone

from telesale_agent.core.interfaces import CallBriefBuilder
from telesale_agent.core.models import CallBrief, JsonObject, TurnContext

class CallBriefProjector(CallBriefBuilder):
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
        previous_brief = context.state.call_brief
        if (
            not context.identity.customer_id
            and previous_brief is not None
            and previous_brief.customer_id is None
        ):
            # Anonymous turns deliberately skip durable customer memory. Keep
            # their normalized facts in this conversation's existing brief so
            # post-persist refreshes and later turns do not discard them.
            raw_facts = previous_brief.remembered_preferences.get("facts", {})
        # Current-turn facts have already been normalized by perception. Overlay
        # them in this read-only projection, including when memory is disabled.
        raw_facts = {**raw_facts, **context.state.memory_deltas}
        canonical_facts = {
            key: value
            for key, value in raw_facts.items()
            if value not in (None, "", [])
        }
        unresolved = canonical_facts.get("unresolved_question")
        unresolved_issues = [unresolved] if isinstance(unresolved, str) else []
        blocker = canonical_facts.get("blocker")
        objections = [blocker] if isinstance(blocker, str) and blocker.strip() else []
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
        contract = _btc_brief_fields(context, canonical_facts, objections, unresolved_issues)
        
        has_history = bool(
            past_sessions
            or history.get("past_orders")
            or memory.get("profile")
            or memory.get("behaviors")
            or memory.get("facts")
            or memory.get("atomic_facts")
            or memory.get("foresights")
            or canonical_facts
        )
        if not has_history:
            current_intent = current_turn["intent"]
            return CallBrief(
                customer_id=context.identity.customer_id,
                customer_name=str(customer_name) if customer_name else None,
                summary=f"New customer context. Current intent: {current_intent}.",
                needs=[f"Current intent: {current_intent}"],
                objections=objections,
                active_promotions=active_promotions,
                verified_customer_data=crm_profile,
                remembered_preferences=remembered_preferences,
                unresolved_issues=unresolved_issues,
                relevant_episodes=past_sessions,
                **contract,
            )

        facts = remembered_preferences.get("facts") or {}
        current_keys = set(context.state.memory_deltas)
        if context.perception:
            current_keys.update(context.perception.memory_deltas)
        # Prioritize facts mentioned now without resurrecting deltas rejected by
        # persistence: values still come from the current canonical projection.
        fact_items = (
            [(key, value) for key, value in facts.items() if key in current_keys]
            + [(key, value) for key, value in facts.items() if key not in current_keys][-8:]
        )
        extracted_needs = [
            f"{key}: {value}" for key, value in fact_items
            if key not in {"blocker", "unresolved_question"}
        ][:8]

        ep_summaries = []
        for ep in past_sessions:
            if not isinstance(ep, dict):
                continue
            episode_text = ep.get("summary") or ep.get("content")
            if episode_text:
                compact = " ".join(str(episode_text).split())
                ep_summaries.append(compact[-600:])

        # Prefer current canonical facts over older episode prose, so explicit
        # corrections made in this turn are visible in the returned brief.
        if extracted_needs:
            summary = f"Customer facts: {', '.join(extracted_needs[:3])}"
        elif objections:
            summary = f"Customer concern: {objections[0]}"
        elif unresolved_issues:
            summary = f"Pending question: {unresolved_issues[0]}"
        elif ep_summaries:
            summary = " | ".join(ep_summaries[-2:])
        else:
            summary = "Returning customer."

        needs = extracted_needs

        return CallBrief(
            customer_id=context.identity.customer_id,
            customer_name=str(customer_name) if customer_name else None,
            summary=summary,
            needs=needs,
            objections=objections,
            active_promotions=active_promotions,
            verified_customer_data=crm_profile,
            remembered_preferences=remembered_preferences,
            unresolved_issues=unresolved_issues,
            relevant_episodes=past_sessions,
            **contract,
        )


def _btc_brief_fields(
    context: TurnContext, facts: JsonObject, objections: list[str], questions: list[str],
) -> JsonObject:
    profile = context.state.customer_profile or {}
    memory = context.state.customer_memory or {}
    sessions = {}
    for session in [*profile.get("sessions", []), *memory.get("episodes", [])]:
        session_id = session.get("session_id") or session.get("conversation_id")
        if session_id == context.state.conversation_id:
            continue
        sessions[session_id or str(session)] = session
    previous = sorted(sessions.values(), key=lambda session: str(session.get("date") or session.get("timestamp") or ""))
    last = None
    if previous:
        session = previous[-1]
        last = {key: str(session[key]) for key in ("session_id", "date", "channel", "summary")
                if session.get(key) is not None}
        if "session_id" not in last and session.get("conversation_id"):
            last["session_id"] = str(session["conversation_id"])
        outcome = session.get("outcome")
        last["outcome"] = outcome if outcome in {"hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"} else "khac"
    products = [{key: value for key, value in product.items() if value is not None}
                for product in facts.get("basket_unit_quotes", [])]
    sku = facts.get("variant_sku") or facts.get("product_advised")
    if sku and not products:
        product = {"sku": str(sku), "promo_code": facts.get("promo_code"), "promo_still_active": None}
        if isinstance(facts.get("price_quoted_vnd"), (int, float)):
            product["price_quoted_vnd"] = int(facts["price_quoted_vnd"])
        if facts.get("price_quoted_on"):
            product["quoted_on"] = str(facts["price_quoted_on"])
        products.append(product)
    prior = context.state.call_brief
    if prior:
        for product in products:
            previous_product = next((item for item in prior.products_advised
                                     if item["sku"] == product["sku"]
                                     and item.get("promo_code") == product.get("promo_code")), None)
            if previous_product:
                product["promo_still_active"] = previous_product.get("promo_still_active")
    returning = bool(previous or profile.get("orders") or memory.get("facts") or memory.get("profile"))
    if prior:
        returning = prior.is_returning
    name = profile.get("name") or "anh/chị"
    return {
        "customer_phone": profile.get("phone") or context.identity.phone or context.input.customer_hint or "",
        "honorific": profile.get("honorific"), "is_returning": returning,
        "n_previous_sessions": len(previous), "last_session": last,
        "profile_facts": {"facts": facts, "atomic_facts": memory.get("atomic_facts", [])},
        "products_advised": products, "orders": profile.get("orders", []),
        "open_blockers": objections, "open_questions": questions,
        "must_not_ask": sorted(facts),
        "suggested_opening": (
            f"Chào {name}, em xin tiếp tục nội dung mình đã trao đổi." if returning
            else f"Chào {name}, em có thể hỗ trợ gì ạ?"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latency_ms": prior.latency_ms if prior else 0,
        "precomputed_parts": ["persisted_" + key for key in (
            "facts", "episodes", "atomic_facts", "foresights",
        ) if memory.get(key)],
        "stale_warnings": list(prior.stale_warnings) if prior else [],
    }


class FreshCallBrief:
    """Refresh volatile evidence before finishing the measured call brief."""
    def __init__(self, builder, db):
        self.builder, self.db = builder, db

    async def build_call_brief(self, context):
        brief = await self.builder.build_call_brief(context)
        if context.state.turn_number == 0:
            facts = (context.state.customer_memory or {}).get("facts",{})
            sku = facts.get("product_advised") or facts.get("variant_sku")
            on = date.fromisoformat(context.input.metadata.get("call_date") or date.today().isoformat())
            current = {"checked_on":on.isoformat(),
                       "crm_profile_and_order_history":"reloaded by customer_context.hydrate",
                       "cross_channel_interactions":"not available in current CRM adapter"}
            if sku:
                current["inventory"] = self.db.check_stock(sku,on)
                profile = context.state.customer_profile or {}
                products = self.db.search_products(sku=sku).get("items",[])
                cart_skus = [sku] + [product["sku"] for product in products if product.get("sku")]
                current["active_promotions"] = self.db.get_active_promotions(
                    cart_skus, [p.get("category","") for p in products], profile.get("region"), on)
                brief.active_promotions = current["active_promotions"]
                active_codes = {promo.get("promo_code") or promo.get("promotion_id")
                                for promo in brief.active_promotions}
                for product in brief.products_advised:
                    code = product.get("promo_code")
                    if code:
                        product["promo_still_active"] = code in active_codes
                        if code not in active_codes:
                            brief.stale_warnings.append(
                                f"Ưu đãi {code} đã báo trước đây không còn được xác nhận hiệu lực."
                            )
                if not current["inventory"].get("in_stock"):
                    brief.stale_warnings.append(f"Sản phẩm {sku} hiện không còn hàng để bán.")
            brief.verified_customer_data = {**brief.verified_customer_data,"freshness_check":current}
        return brief
