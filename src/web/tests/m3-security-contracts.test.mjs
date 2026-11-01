// Audit instrumentation only: compile selected real backend handlers in an
// isolated namespace with synthetic state. No backend imports, DB, HTTP or LLM.
// Passing diagnostics reproduce findings; they do NOT pass the M3 security gate.
import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createPurchaseStore } from '../utils/commerce.ts';

const python = String.raw`
import ast, asyncio, copy, json, os, re, secrets, sys, unicodedata
from types import SimpleNamespace as NS
from unittest.mock import patch

source = ast.parse(open(sys.argv[1], encoding='utf-8').read())
identity_source = ast.parse(open(sys.argv[2], encoding='utf-8').read())
class HTTPError(Exception):
    def __init__(self, status_code, detail): self.status_code = status_code
class InputError(Exception): pass

def load(tree, names, namespace):
    selected = [copy.deepcopy(n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    for n in selected:
        n.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<m3-readonly-contract-probe>', 'exec'), namespace)

async def probe():
    sid = '10000000-0000-4000-8000-000000000001'
    state = NS(conversation_id=sid, owner='synthetic-user-a', customer_profile={'owner':'synthetic-user-a'}, customer_memory={'synthetic':True}, past_history={'synthetic':True})
    calls = []
    async def run_turn(turn, existing):
        calls.append((turn.customer_hint, existing.owner))
        return NS(state=existing, response_text='synthetic response', perception=None, retrieved=None, tool_calls=[], memory_writes=[], usage={})
    namespace = dict(os=os, secrets=secrets, asyncio=asyncio, Header=lambda **kw:None, HTTPException=HTTPError,
        harness=NS(run_turn=run_turn), sessions={sid:state}, session_locks={},
        provider_cooldown=NS(remaining=lambda:0), Channel=NS(VOICE='voice'),
        AudioTooLargeError=InputError, AudioInputError=InputError, ASRUnavailableError=InputError)
    load(source, {'require_api_key','run_chat_turn','turn_payload','clear_session'}, namespace)
    with patch.dict(os.environ, {'API_KEY':'', 'ENABLE_DEBUG_RESPONSE':'false'}, clear=True):
        namespace['require_api_key']()
        anonymous_allowed = True
        turn = NS(conversation_id=sid, text='synthetic question', channel='text', customer_hint='synthetic-user-b', metadata={})
        await namespace['run_chat_turn'](turn)
        reused_foreign_state = calls[-1] == ('synthetic-user-b','synthetic-user-a')
        os.environ['ENABLE_DEBUG_RESPONSE'] = 'true'
        response = await namespace['run_chat_turn'](turn)
        debug_exposes_profile = response['debug']['crm_profile']['owner'] == 'synthetic-user-a'
        await namespace['clear_session'](sid)
        foreign_state_deleted = sid not in namespace['sessions']
        os.environ['API_KEY'] = 'm3-synthetic-service-key'
        try:
            namespace['require_api_key']()
            configured_guard_rejects_missing = False
        except HTTPError as e:
            configured_guard_rejects_missing = e.status_code == 401
        namespace['require_api_key']('m3-synthetic-service-key')
    identity = dict(re=re, unicodedata=unicodedata, IdentityResolver=object, CustomerIdentity=lambda **kw:NS(**kw),
        db_client=NS(get_customer=lambda **kw: {'found':True,'customer_id':'synthetic-user-b','name':'Synthetic B'}))
    load(identity_source, {'_normalized_identity_text','_identity_tokens','HintIdentityResolver'}, identity)
    resolved = await identity['HintIdentityResolver']().resolve_identity(NS(input=NS(customer_hint='0000000000', text='synthetic')))
    routes=[]
    for n in source.body:
        for d in getattr(n,'decorator_list',[]):
            if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='app' and d.args and isinstance(d.args[0],ast.Constant):
                routes.append([d.func.attr.upper(),d.args[0].value])
    return dict(routes=routes,anonymous_allowed=anonymous_allowed,configured_guard_rejects_missing=configured_guard_rejects_missing,
        reused_foreign_state=reused_foreign_state,foreign_state_deleted=foreign_state_deleted,
        debug_exposes_profile=debug_exposes_profile,hint_trusted_without_proof=resolved.customer_id=='synthetic-user-b' and resolved.confidence==1.0)
print(json.dumps(asyncio.run(probe())))
`;
const pythonCommand = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const processResult = spawnSync(pythonCommand, ['-I', '-B', '-c', python,
  fileURLToPath(new URL('../../telesale_agent/entrypoints/api/chat.py', import.meta.url)),
  fileURLToPath(new URL('../../telesale_agent/adapters/mock/identity.py', import.meta.url))], { encoding:'utf8' });
assert.equal(processResult.status, 0, processResult.stderr || processResult.error?.message);
const findings = JSON.parse(processResult.stdout);

test('M3 selected chat module handlers retain text/audio/session/health routes', () => {
  assert.deepEqual(findings.routes, [['POST','/api/chat'],['POST','/api/chat/audio'],['DELETE','/api/sessions/{conversation_id}'],['GET','/'],['GET','/health']]);
});
test('M3 finding: service key rejects missing keys when configured but permits anonymous calls by default', () => {
  assert.equal(findings.configured_guard_rejects_missing, true);
  assert.equal(findings.anonymous_allowed, true);
});
test('M3 critical finding: selected handlers reuse and delete foreign synthetic conversation state by supplied ID', () => {
  assert.equal(findings.reused_foreign_state, true);
  assert.equal(findings.foreign_state_deleted, true);
});
test('M3 critical finding: phone hint is trusted without authentication; debug can expose synthetic CRM state', () => {
  assert.equal(findings.hint_trusted_without_proof, true);
  assert.equal(findings.debug_exposes_profile, true);
});
test('M3 finding: guest cart shares browser storage across tabs; it is not a customer-owned cart', () => {
  const storage=()=>{const map=new Map();return {getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)};};
  const sharedLocal=storage(), sessionA=storage(), sessionB=storage();
  const a=createPurchaseStore(()=>sharedLocal,()=>sessionA), b=createPurchaseStore(()=>sharedLocal,()=>sessionB);
  a.hydrate();a.add({productSku:'SKU-AP-X',sku:'SKU-AP-X',quantity:1});b.hydrate();
  assert.deepEqual(b.getSnapshot().cart,a.getSnapshot().cart);
  assert.equal(b.getSnapshot().orders.length,0);
});
