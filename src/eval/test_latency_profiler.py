"""Profiling complete responses must never replay calls or double count children."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.latency_profiler import Timeline,attach_profiler,profiling_hooks,summarize_profiles
from telesale_agent.application.deepagent import turn
from telesale_agent.adapters.llm.usage_tracking import usage_stage
from telesale_agent.core.models import TurnInput
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import tool


class ProfileAccountingTests(unittest.TestCase):
    def test_nested_requests_are_not_added_to_stage_totals(self):
        clock = [0.0]
        with patch('eval.latency_profiler.time.perf_counter',lambda:clock[0]):
            timeline = Timeline(0)
            with timeline.span('turn','turn'):
                with timeline.span('perception','stage'):
                    clock[0] = .1
                    with timeline.span('llm.perception','llm'):
                        clock[0] = 1
                with timeline.span('main_agent','stage'):
                    clock[0] = 2
                clock[0] = 2.1
            profile = timeline.export()
        summary = summarize_profiles({('s','c'):[{'latency':{'profile':profile}}]})
        self.assertEqual(profile['stage_total_ms'],2000)
        self.assertEqual(profile['unattributed_ms'],100)
        self.assertEqual(sum(summary['stage_totals_ms'].values()),2000)
        self.assertEqual(profile['spans'][2]['duration_ms'],900)


class ProfileIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_graph_model_tool_loop_is_profiled_without_changing_answer(self):
        from langchain.agents import create_agent
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage,ToolMessage
        from langchain_core.outputs import ChatGeneration,ChatResult
        from telesale_agent.application.deepagent.tools.routing import IntentToolRoutingMiddleware,TelesaleAgentRuntimeContext
        from telesale_agent.core.models import CustomerIdentity,CallBrief
        class ToolModel(BaseChatModel):
            @property
            def _llm_type(self):
                return 'profile-test'
            def _generate(self,messages,stop=None,run_manager=None,**kwargs):
                if isinstance(messages[-1],ToolMessage):
                    answer = AIMessage(content='Chính sách đã kiểm tra.')
                else:
                    answer = AIMessage(content='',tool_calls=[{'name':'search_policy','args':{},'id':'read'}])
                return ChatResult(generations=[ChatGeneration(message=answer)])
            def bind_tools(self,tools,**kwargs):
                return self
        @tool
        async def search_policy() -> str:
            """Read a local policy fixture."""
            return 'Đổi trả 7 ngày.'
        async def identity(context):
            return CustomerIdentity(customer_id='profile-test')
        async def brief(context):
            return CallBrief(customer_id='profile-test')
        async def reads(*args):
            return [],frozenset({'search_policy'})
        async def mutations(context,allowed,verified):
            return [],allowed
        async def run(*args,**kwargs):
            return await turn.run_turn_impl(harness,*args,**kwargs)
        with patch.dict('os.environ',{'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}),profiling_hooks():
            graph = create_agent(ToolModel(),tools=[search_policy],middleware=[IntentToolRoutingMiddleware()],context_schema=TelesaleAgentRuntimeContext)
            harness = SimpleNamespace(agent=graph,asr=None,identity=SimpleNamespace(resolve_identity=identity),
                call_brief=SimpleNamespace(build_call_brief=brief),perceive=None,retrieve=None,
                customer_context=None,guardrail=None,persist=None,_prefetch_read_tools=reads,
                _execute_confirmed_mutation=mutations,run_turn=run)
            attach_profiler(harness)
            result = await harness.run_turn(TurnInput('graph-profile',text='chính sách'))
        spans = result.latency['profile']['spans']
        self.assertEqual(result.response_text.strip(),'Chính sách đã kiểm tra.')
        self.assertEqual(len([s for s in spans if s['kind']=='llm']),2)
        self.assertEqual(len([s for s in spans if s['kind']=='tool']),1)
        self.assertEqual(result.latency['measurement_mode'],'non_streaming')
        self.assertEqual(result.latency['ttft_ms'],result.latency['total_ms'])
        self.assertLessEqual(result.latency['profile']['stage_total_ms'],result.latency['profile']['backend_ms']+.1)

    async def test_callbacks_capture_model_and_tool_without_replay(self):
        calls = []
        @tool
        async def lookup() -> dict:
            """Read a test product without external I/O."""
            calls.append('lookup')
            return {'price':10}
        model = FakeListChatModel(responses=['Xin chào chị.'])
        async def perceive(context):
            with usage_stage('perception'):
                await model.ainvoke('NLU')
        async def reads(*args):
            await lookup.ainvoke({})
        async def invoke(*args,**kwargs):
            return await model.ainvoke('response')
        async def run(turn_input,state=None):
            context = SimpleNamespace()
            await harness.perceive.perceive(context)
            await harness._prefetch_read_tools(context)
            with usage_stage('main_agent'):
                answer = await harness.agent.ainvoke({})
            return SimpleNamespace(latency={},response_text=answer.content)
        harness = SimpleNamespace(perceive=SimpleNamespace(perceive=perceive),
            _prefetch_read_tools=reads,agent=SimpleNamespace(ainvoke=invoke),run_turn=run)
        original_guard = turn.prepare_response
        with patch.dict('os.environ',{'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}), profiling_hooks():
            attach_profiler(harness)
            result = await harness.run_turn(TurnInput('profile',text='xin chào'))
        self.assertIs(turn.prepare_response,original_guard)
        profile = result.latency['profile']
        spans = profile['spans']
        requests = [s for s in spans if s['kind']=='llm']
        self.assertEqual(calls,['lookup'])
        self.assertEqual(len(requests),2)
        self.assertEqual({s['stage'] for s in requests},{'perception','main_agent'})
        self.assertEqual(len([s for s in spans if s['kind']=='tool']),1)
        self.assertEqual(result.response_text,'Xin chào chị.')
        self.assertLessEqual(profile['stage_total_ms'],profile['backend_ms']+.1)
        self.assertTrue(all(s['status']=='completed' for s in spans))

    async def test_failure_still_exports_diagnostic_spans(self):
        async def run(*args,**kwargs):
            raise TimeoutError()
        harness = SimpleNamespace(agent=SimpleNamespace(),run_turn=run)
        attach_profiler(harness)
        with self.assertRaises(TimeoutError) as caught:
            await harness.run_turn(TurnInput('failed',text='hello'))
        self.assertEqual(caught.exception.telesale_profile['spans'][0]['status'],'error')


if __name__=='__main__':
    unittest.main()
