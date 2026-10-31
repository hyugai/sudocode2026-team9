import assert from 'node:assert/strict';
import test from 'node:test';
import { readGuestSession, writeGuestSession } from '../utils/conversation-session.ts';
import { createChatClient } from '../utils/chat-api.ts';
const saved={messages:[{role:'agent',text:'Xin chào'},{role:'user',text:'Tư vấn SKU-AP-X'}],sessionId:'8af14e01-e4a6-4730-9a63-1c7b8392942d',input:'Bản nháp',customerPhone:'0901234567',voicePreview:true,consultation:{sku:'SKU-AP-X',name:'AirPure X',price:'4.890.000₫',quantity:1}};
test('Guest snapshot restores conversation identity, draft, mode and explicit context',()=>{
 assert.deepEqual(readGuestSession(writeGuestSession(saved)),saved);assert.equal(readGuestSession(null),null);
});
test('Guest restore rejects invalid identities, roles and stale schemas',()=>{
 for(const patch of [{sessionId:'someone-else'},{messages:[{role:['agent'],text:'x'}]},{consultation:{...saved.consultation,quantity:0}},{version:2}])assert.throws(()=>readGuestSession(JSON.stringify({...saved,version:1,...patch})));
 assert.throws(()=>readGuestSession('{bad'));assert.throws(()=>readGuestSession('x'.repeat(2000001)));
});
test('Snapshots bound restored messages and never persist audio or debug/CRM data',()=>{
 const raw=writeGuestSession({...saved,messages:Array.from({length:302},()=>({role:'agent',text:'x'})),audioFile:{private:true},debugLogs:[{crm:'private'}]});
 // Persistence explicitly selects the guest fields at the hook boundary.
 const clean=JSON.parse(raw);
 assert.equal(clean.messages.length,300);assert.equal(clean.audioFile,undefined);assert.equal(clean.debugLogs,undefined);
});
test('End conversation uses the existing DELETE contract and requires the matching receipt',async()=>{
 const calls=[];const client=createChatClient('https://example.invalid',async(url,options)=>{calls.push([url,options.method]);return Response.json({status:'cleared',conversation_id:saved.sessionId});});
 await client.clearSession(saved.sessionId);assert.deepEqual(calls,[[`https://example.invalid/api/sessions/${saved.sessionId}`,'DELETE']]);
 const wrong=createChatClient('',async()=>Response.json({status:'cleared',conversation_id:'wrong'}));await assert.rejects(wrong.clearSession(saved.sessionId),/đúng hội thoại/);
});
test('Unauthorized and unavailable session deletion fail explicitly without retries',async()=>{
 for(const status of [401,403,503]){let calls=0;const client=createChatClient('',async()=>{calls++;return Response.json({detail:'unavailable'},{status});});await assert.rejects(client.clearSession(saved.sessionId),/vẫn được giữ/);assert.equal(calls,1);}
 const client=createChatClient('',async()=>{throw new Error('offline');});await assert.rejects(client.clearSession(saved.sessionId),/Không kết nối/);
});
