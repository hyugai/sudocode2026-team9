"""Read-only Live dispatcher. No model argument can grant mutation permissions."""
import asyncio
import json
from telesale_agent.core.business_time import business_date
from telesale_agent.application.conversation.tool_policy import select_tools_for_turn
from telesale_agent.application.tools.protocol import canonical_tool_name, canonical_tool_args, decode_tool_result
from telesale_agent.application.realtime.context import READ_TOOLS, brief_data, tool_declarations, public_data
from telesale_agent.application.deepagent.context.order import _delivery_address


def _valid_value(value, schema):
    """Validate the narrow public schemas, including nested basket lines."""
    kind = schema["type"]
    if kind == "object":
        return (isinstance(value, dict) and not (set(value) - set(schema["properties"]))
                and all(key in value for key in schema.get("required", []))
                and all(_valid_value(item, schema["properties"][key]) for key, item in value.items()))
    if kind == "array":
        return (isinstance(value, list) and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100)
                and all(_valid_value(item, schema["items"]) for item in value))
    if kind == "string":
        return isinstance(value, str) and schema.get("minLength", 0) <= len(value) <= 1000
    if kind == "integer":
        return type(value) is int and schema.get("minimum", 0) <= value <= schema.get("maximum", 10000)
    return False


async def dispatch(services, settings, state, context, name, args, call_id):
    if settings.tools_mode == "off":
        return {"error": "tools_disabled"}, None
    schemas = {d["name"]: d["parameters_json_schema"] for d in
               tool_declarations(services.mcp_tools, settings.tools_mode)}
    if name not in schemas or not isinstance(args, dict):
        return {"error": "tool_not_allowed"}, None
    schema = schemas[name]
    if not _valid_value(args, schema):
        return {"error": "invalid_arguments"}, None
    if name == "get_order_quote" and sum(line["qty"] for line in args["lines"]) > 100:
        return {"error": "invalid_arguments"}, None
    if name == "get_customer_context":
        if services.customer_context and context:
            await services.customer_context.refresh_memory(context)
        if services.call_brief and context:
            state.call_brief = await services.call_brief.build_call_brief(context)
        return {"context": brief_data(state), "mode": "read_only"}, None
    if not context or not context.input.text:
        return {"error": "needs_clarification", "message": "Chưa có transcript hoàn chỉnh; hỏi lại khách."}, None
    if name not in READ_TOOLS:
        return {"error": "tool_not_allowed"}, None
    facts = (state.customer_memory or {}).get("facts", {})
    allowed = select_tools_for_turn(context.perception, context.input.text, facts)
    if name not in allowed and name != "search_customer_memory_archive":
        return {"error": "tool_not_allowed_for_turn"}, None
    arguments = dict(args)
    if name in {"get_pricing_quote", "get_order_quote"}:
        arguments.update(customer_id=state.identity.customer_id if state.identity else None,
                         customer_phone=state.identity.phone if state.identity else None)
        arguments["address"] = _delivery_address(context)
    if name == "search_customer_memory_archive":
        arguments["customer_id"] = state.identity.customer_id if state.identity else None
        if not arguments["customer_id"]:
            return {"error": "identity_required"}, None
    if name in {"get_pricing_quote", "get_order_quote", "check_inventory"}:
        arguments["on"] = business_date(context.input.metadata.get("call_date")).isoformat()
    try:
        if name == "search_customer_memory_archive":
            raw = await asyncio.wait_for(asyncio.to_thread(
                services.memory.search_archive, arguments["customer_id"], arguments["query"]),
                settings.tool_timeout)
        else:
            raw = await asyncio.wait_for(services.mcp_tools[name].ainvoke(arguments), settings.tool_timeout)
        result = decode_tool_result(raw)
    except TimeoutError:
        result = {"error": "tool_timeout"}
    except Exception:
        result = {"error": "tool_failed"}
    evidence = {"id": call_id, "name": canonical_tool_name(name),
                "args": canonical_tool_args(canonical_tool_name(name), arguments), "result": result}
    # Memory receives verified evidence; the model receives a bounded, PII-masked view.
    public = public_data(result)
    if len(json.dumps(public, ensure_ascii=False)) > 16000:
        return {"error": "result_too_large", "message": "Thu hẹp truy vấn."}, evidence
    return (public if isinstance(result, dict) else {"result": public}), evidence
