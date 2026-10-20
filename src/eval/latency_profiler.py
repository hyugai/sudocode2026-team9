"""Opt-in, process-local wall-clock profiling; never send extra model requests.

Stage spans partition a turn. Operation/LLM/tool spans explain their parents
and must not be added to stage totals. Provider callbacks measure client-side
request time (including any SDK retry), not provider-internal compute time.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
from itertools import count
import time
from unittest.mock import patch

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from telesale_agent.adapters.llm.usage_tracking import _ACTIVE_STAGE
from telesale_agent.application.deepagent.streaming import chunk_text

_ACTIVE = ContextVar("eval_latency_profile", default=None)
_PARENT = ContextVar("eval_latency_parent", default=None)
_CALLBACK = ContextVar("eval_latency_callback", default=None)
register_configure_hook(_CALLBACK, True)


class Timeline:
    def __init__(self, origin):
        self.origin = origin
        self.spans = []
        self.marks = []
        self.ids = count()

    def start(self, name, kind, **fields):
        record = {"id":next(self.ids), "parent_id":_PARENT.get(),
                  "name":name, "kind":kind, "start_ms":(time.perf_counter()-self.origin)*1000,
                  "end_ms":None, **fields}
        self.spans.append(record)
        return record

    def stop(self, record, status="completed", **fields):
        if record["end_ms"] is None:
            record.update(end_ms=(time.perf_counter()-self.origin)*1000, status=status, **fields)

    @contextmanager
    def span(self, name, kind="operation"):
        record = self.start(name,kind)
        token = _PARENT.set(record["id"])
        try:
            yield record
        except BaseException as exc:
            self.stop(record,"error",error_type=type(exc).__name__)
            raise
        else:
            self.stop(record)
        finally:
            _PARENT.reset(token)

    def mark(self, name):
        self.marks.append({"name":name,"at_ms":(time.perf_counter()-self.origin)*1000})

    def export(self):
        end = (time.perf_counter()-self.origin)*1000
        spans = []
        for item in self.spans:
            record = dict(item)
            if record["end_ms"] is None:
                record.update(end_ms=end,status="incomplete")
            record["duration_ms"] = round(record["end_ms"]-record["start_ms"],3)
            for key,value in list(record.items()):
                if key.endswith("_ms") and value is not None:
                    record[key] = round(value,3)
            spans.append(record)
        root = next((s for s in spans if s["kind"]=="turn"),None)
        stages = [s for s in spans if root and s["parent_id"]==root["id"] and s["kind"]=="stage"]
        measured = sum(s["duration_ms"] for s in stages)
        return {"schema_version":1,"boundary":"perf_counter; harness arrival; ASR included in timeline",
                "backend_ms":round(end,3),"stage_total_ms":round(measured,3),
                "unattributed_ms":round(max(0,end-measured),3),
                "stage_accounting":"Only direct stage children of turn are additive; nested spans overlap.",
                "spans":spans,"marks":[{**m,"at_ms":round(m["at_ms"],3)} for m in self.marks]}


@contextmanager
def span(name, kind="operation"):
    timeline = _ACTIVE.get()
    if timeline is None:
        yield None
    else:
        with timeline.span(name,kind) as record:
            yield record


def timed(function, name, kind="operation"):
    if inspect.isasyncgenfunction(function):
        @wraps(function)
        async def generator(*args,**kwargs):
            with span(name,kind):
                async for item in function(*args,**kwargs):
                    yield item
        return generator
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def asynchronous(*args,**kwargs):
            with span(name,kind):
                return await function(*args,**kwargs)
        return asynchronous
    @wraps(function)
    def synchronous(*args,**kwargs):
        with span(name,kind):
            return function(*args,**kwargs)
    return synchronous


class RequestTimings(BaseCallbackHandler):
    # Inline clock bookkeeping avoids executor scheduling in timestamp hooks.
    run_inline = True

    def __init__(self, timeline):
        self.timeline = timeline
        self.runs = {}

    def _start(self, run_id, name, kind):
        key = str(run_id)
        if key not in self.runs:
            self.runs[key] = self.timeline.start(name,kind,stage=_ACTIVE_STAGE.get())

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start(run_id,"llm."+_ACTIVE_STAGE.get(),"llm")

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._start(run_id,"llm."+_ACTIVE_STAGE.get(),"llm")

    def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        record = self.runs.get(str(run_id))
        if record is None:
            return
        now = (time.perf_counter()-self.timeline.origin)*1000
        record.setdefault("first_chunk_at_ms",now)
        message = getattr(chunk,"message",None)
        if message is not None and chunk_text(message):
            record.setdefault("first_public_text_at_ms",now)

    def on_llm_end(self, response, *, run_id, **kwargs):
        record = self.runs.get(str(run_id))
        if record is None:
            return
        finish = None
        reasoning = None
        for group in getattr(response,"generations",[]) or []:
            for generation in group:
                message = getattr(generation,"message",None)
                metadata = getattr(message,"response_metadata",None) or {}
                finish = finish or metadata.get("finish_reason") or (getattr(generation,"generation_info",None) or {}).get("finish_reason")
                details = (getattr(message,"usage_metadata",None) or {}).get("output_token_details") or {}
                if details.get("reasoning") is not None:
                    reasoning = (reasoning or 0)+details["reasoning"]
        for key in ("first_chunk","first_public_text"):
            if key+"_at_ms" in record:
                record[key+"_latency_ms"] = record[key+"_at_ms"]-record["start_ms"]
        self.timeline.stop(record,finish_reason=finish,reasoning_tokens=reasoning)

    def on_llm_error(self, error, *, run_id, **kwargs):
        record = self.runs.get(str(run_id))
        if record is not None:
            self.timeline.stop(record,"error",error_type=type(error).__name__)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._start(run_id,"tool."+(serialized.get("name") or "unknown"),"tool")

    def on_tool_end(self, output, *, run_id, **kwargs):
        record = self.runs.get(str(run_id))
        if record is not None:
            failed = (isinstance(output,dict) and bool(output.get("error"))) or getattr(output,"status",None)=="error"
            self.timeline.stop(record,"tool_error" if failed else "completed")

    def on_tool_error(self, error, *, run_id, **kwargs):
        record = self.runs.get(str(run_id))
        if record is not None:
            self.timeline.stop(record,"error",error_type=type(error).__name__)


class _AgentProxy:
    def __init__(self, agent):
        self.agent = agent

    def __getattr__(self, name):
        value = getattr(self.agent,name)
        if name=="astream":
            async def stream(*args,**kwargs):
                with span("main_agent","stage"):
                    async for event in value(*args,**kwargs):
                        yield event
            return stream
        if name=="ainvoke":
            return timed(value,"main_agent","stage")
        return value


def attach_profiler(harness):
    """Wrap this eval harness only, after its FreshCallBrief wrapper is set."""
    def wrap(obj, method, name, kind="operation"):
        if obj is not None and callable(getattr(obj,method,None)):
            setattr(obj,method,timed(getattr(obj,method),name,kind))

    for attr,method,name in (
        ("asr","transcribe","asr"),("identity","resolve_identity","identity"),
        ("perceive","perceive","perception"),("retrieve","retrieve","retrieval"),
        ("customer_context","hydrate","customer_hydrate"),
        ("customer_context","refresh_memory","memory_refresh"),
        ("call_brief","build_call_brief","call_brief"),("persist","persist","persistence"),
    ):
        wrap(getattr(harness,attr,None),method,name,"stage")
    wrap(getattr(getattr(harness,"call_brief",None),"builder",None),"build_call_brief","call_brief_projection")
    wrap(getattr(harness,"crm",None),"retrieve_profile","crm_profile")
    wrap(getattr(harness,"crm",None),"precompute_brief","crm_order_history")
    wrap(getattr(harness,"guardrail",None),"check","pii_guard")
    for method in ("load","upsert_fact","record_atomic_fact","record_episode","record_foresight","save_snapshot","search_archive"):
        wrap(getattr(harness,"memory",None),method,"memory."+method)
    wrap(harness,"_prefetch_read_tools","read_prefetch","stage")
    wrap(harness,"_execute_confirmed_mutation","confirmed_mutation","stage")
    harness.agent = _AgentProxy(harness.agent)
    original = harness.run_turn

    @wraps(original)
    async def run(turn_input,state=None,**kwargs):
        output = kwargs.get("response_stream")
        origin = output.started_at if output is not None else turn_input.metadata.get("_latency_started_at",time.perf_counter())
        timeline = Timeline(origin)
        active = _ACTIVE.set(timeline)
        parent = _PARENT.set(None)
        callbacks = _CALLBACK.set(RequestTimings(timeline))
        if output is not None:
            output.eval_profile = timeline
        try:
            with timeline.span("turn","turn"):
                result = await original(turn_input,state,**kwargs)
        except BaseException as exc:
            exc.telesale_profile = timeline.export()
            raise
        else:
            result.latency["profile"] = timeline.export()
            return result
        finally:
            _CALLBACK.reset(callbacks)
            _PARENT.reset(parent)
            _ACTIVE.reset(active)
    harness.run_turn = run


@contextmanager
def profiling_hooks():
    """Restore every module patch on exit; no application files are changed."""
    from telesale_agent.application.deepagent import turn, streaming
    from telesale_agent.adapters.db.client import db_client
    from telesale_agent.adapters.llm import llm_persist
    from telesale_agent.adapters.memory import turn_persist, write_session

    with ExitStack() as stack:
        for name,label,kind in (
            ("normalize_asr_transcript","normalize_audio_text","stage"),
            ("normalize_chat_text","normalize_chat_text","stage"),
            ("build_base_user_message","context_build","stage"),
            ("select_tools_for_turn","tool_routing","stage"),
            ("append_orchestration_context","context_tool_evidence","stage"),
            ("prepare_response","response_guard","stage"),
        ):
            stack.enter_context(patch.object(turn,name,timed(getattr(turn,name),label,kind)))
        for name in ("get_customer","get_customer_by_id","search_products","check_stock","get_active_promotions"):
            stack.enter_context(patch.object(db_client,name,timed(getattr(db_client,name),"db."+name)))
        for module in (llm_persist,turn_persist):
            stack.enter_context(patch.object(module,"persist_turn_memory",timed(module.persist_turn_memory,"canonical_facts")))
        stack.enter_context(patch.object(write_session.TurnMemoryWriteSession,"commit",timed(write_session.TurnMemoryWriteSession.commit,"snapshot_commit")))
        original_send = streaming.AnswerStream.send
        original_emitted = streaming.AnswerStream.emitted

        @wraps(original_send)
        async def send(output,event):
            with span("stream_delivery_wait","stage"):
                return await original_send(output,event)

        @wraps(original_emitted)
        def emitted(output,event):
            result = original_emitted(output,event)
            timeline = getattr(output,"eval_profile",None)
            if timeline is not None and event["type"] in {"delta","replace"} and event.get("text"):
                timeline.mark("answer_emit")
            return result

        stack.enter_context(patch.object(streaming.AnswerStream,"send",send))
        stack.enter_context(patch.object(streaming.AnswerStream,"emitted",emitted))
        yield


def summarize_profiles(trace):
    """Sum stage parents only. Nested LLM/tool totals are reported separately."""
    profiles = [r.get("latency",{}).get("profile") for rows in trace.values() for r in rows]
    profiles = [p for p in profiles if p]
    groups = {}
    for profile in profiles:
        root = next(s for s in profile["spans"] if s["kind"]=="turn")
        for item in profile["spans"]:
            if item["kind"]=="stage" and item["parent_id"]==root["id"]:
                groups[item["name"]] = groups.get(item["name"],0)+item["duration_ms"]
    return {"turns":len(profiles),"includes_warmup":True,
            "backend_total_ms":round(sum(p["backend_ms"] for p in profiles),3),
            "unattributed_ms":round(sum(p["unattributed_ms"] for p in profiles),3),
            "stage_totals_ms":{k:round(v,3) for k,v in sorted(groups.items(),key=lambda p:-p[1])},
            "note":"Diagnostic all-turn stage totals; official latency still drops 3 warm-up turns. Children overlap their parents."}
