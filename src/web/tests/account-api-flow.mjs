// Run by tests/test_auth_api.py against its disposable PostgreSQL-backed API.
import assert from "node:assert/strict";
import { createAuthClient } from "../utils/auth-api.ts";
import { createChatClient } from "../utils/chat-api.ts";
import { conversationApi } from "../utils/conversation-api.ts";
import { readCallBrief } from "../utils/call-brief.ts";
import { syncAuthOwner } from "../utils/auth-storage.ts";
import { accountConversationKey } from "../utils/conversation-api.ts";
import { conversationStorageKey } from "../utils/conversation-session.ts";
import { CART_KEY, SESSION_KEY } from "../utils/commerce.ts";
import { loadChatCatalog, matchChatProducts } from "../utils/chat-products.ts";

const nativeFetch = globalThis.fetch;
const base = process.env.ACCOUNT_FLOW_API;
assert.ok(base);
let cookie = "";
// Node has no browser cookie jar or Origin header. Supply just those browser duties.
globalThis.fetch = async (path, options = {}) => {
  const headers = new Headers(options.headers);
  headers.set("Origin", "http://localhost:3000");
  if (cookie) headers.set("Cookie", cookie);
  const response = await nativeFetch(new URL(path, base), { ...options, headers });
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) cookie = setCookie.split(";", 1)[0];
  return response;
};

const auth = createAuthClient();
const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};
const session = storage();
const local = storage();
session.setItem(conversationStorageKey, "guest draft");
session.setItem(SESSION_KEY, "guest purchase");
local.setItem(CART_KEY, "guest cart");
assert.equal(await auth.me(), null);
await assert.rejects(auth.register("Demo", "short@example.com", "1234567"), /8/);
const user = await auth.register("Demo", "demo@example.com", "Demo2026");
await auth.login("demo@example.com", "Demo2026");
syncAuthOwner(user.id, session, local, true);
assert.equal(session.getItem(conversationStorageKey), null);
assert.equal(session.getItem(SESSION_KEY), null);
assert.equal(local.getItem(CART_KEY), null);
assert.equal((await auth.me()).id, user.id);
const chat = createChatClient(base, fetch, Date.now, true);
assert.equal(await chat.isReady(AbortSignal.timeout(5000)), true);
const conversation = await conversationApi.create("0900000000");
session.setItem(accountConversationKey, conversation.id);
syncAuthOwner(user.id, session, local);
assert.equal(session.getItem(accountConversationKey), conversation.id);
const invalid = await fetch("/api/chat", {
  method: "POST", headers: { "Content-Type": "application/json", "X-Conversation-Mode": "account" },
  body: JSON.stringify({ conversation_id: "invalid", message: "Hello" }),
});
assert.equal(invalid.status, 422);
const drafts = [];
const stages = [];
const send = (message, audioFile = null) => chat.send({
  conversationId: conversation.id, customerPhone: "0900000000", message, audioFile,
}, text => drafts.push(text), stage => stages.push(stage));
const first = await send("Toi can tu van, ngan sach 3000000");
assert.ok(first.message_id);
assert.ok(drafts.length > 0, "UI must receive drafts before the final receipt");
assert.equal(drafts.at(-1), "Draft answer");
assert.equal(first.response, "Final verified answer: SKU-AP-X");
const catalog = await loadChatCatalog();
const [productCard] = matchChatProducts(first.response, catalog);
assert.equal(productCard.sku, "SKU-AP-X");
assert.equal(productCard.name, "Máy lọc không khí AirPure X");
assert.equal(productCard.price, 1234567);
assert.equal(first.latency.measurement_mode, "streaming");
for (const stage of ["processing", "identifying", "analyzing", "brief", "generating", "checking", "saving"]) {
  assert.ok(stages.includes(stage), `Missing actual pipeline stage: ${stage}`);
}
assert.ok(stages.indexOf("analyzing") < stages.indexOf("generating"));
assert.ok(stages.indexOf("checking") < stages.indexOf("saving"));
assert.ok(first.callBrief.needs.some(value => value.includes("3000000")));
const feedback = { rating: "positive", comment: "Useful" };
await conversationApi.putFeedback(first.message_id, feedback);
let saved = await conversationApi.load(conversation.id);
assert.equal(saved.messages.length, 2);
assert.equal(saved.messages[1].content, "Final verified answer: SKU-AP-X");
assert.deepEqual(matchChatProducts(saved.messages[1].content, catalog), [productCard]);
assert.deepEqual(saved.messages.map(message => message.role), ["user", "agent"]);
assert.deepEqual(saved.messages[1].feedback, feedback);
assert.deepEqual(readCallBrief(saved.call_brief), first.callBrief);
assert.equal((await conversationApi.list()).items[0].id, conversation.id);

// A fresh frontend client must resume from the DB, with prior brief facts retained.
const second = await createChatClient(base, fetch, Date.now, true).send({
  conversationId: saved.id.toUpperCase(), customerPhone: saved.customer_phone,
  message: "Hello again", audioFile: null,
});
assert.ok(second.callBrief.needs.some(value => value.includes("3000000")));
const audio = await send("", new File(["synthetic"], "demo.wav", { type: "audio/wav" }));
assert.equal(typeof audio.transcript, "string");
assert.ok(stages.includes("transcribing"));
saved = await conversationApi.load(conversation.id);
assert.equal(saved.turn_number, 3);
assert.equal(saved.messages.length, 6);
assert.deepEqual(readCallBrief(saved.call_brief), audio.callBrief);
// Dropping the browser stream must not cancel the DB commit or replay the turn.
const interrupted = await fetch("/api/chat", {
  method: "POST", headers: { "Content-Type": "application/json", "Accept": "text/event-stream", "X-Conversation-Mode": "account" },
  body: JSON.stringify({ conversation_id: conversation.id, message: "Finish this turn after disconnect" }),
});
const reader = interrupted.body.getReader();
await reader.read();
await reader.cancel();
for (let attempt = 0; attempt < 30; attempt++) {
  saved = await conversationApi.load(conversation.id);
  if (saved.turn_number === 4) break;
  await new Promise(resolve => setTimeout(resolve, 100));
}
assert.equal(saved.turn_number, 4);
assert.equal(saved.messages.length, 8);
assert.equal(saved.messages.at(-1).content, "Final verified answer: SKU-AP-X");
await conversationApi.deleteFeedback(first.message_id);
assert.equal((await conversationApi.load(conversation.id)).messages[1].feedback, null);
await chat.clearSession(conversation.id);
assert.equal((await conversationApi.load(conversation.id)).status, "ended");
await assert.rejects(send("Do not append to ended history"));

await auth.register("Other", "other@example.com", "Demo2026");
await auth.login("other@example.com", "Demo2026");
syncAuthOwner((await auth.me()).id, session, local, true);
assert.equal(session.getItem(accountConversationKey), null);
assert.equal((await conversationApi.list()).items.length, 0);
await assert.rejects(conversationApi.load(conversation.id));
await assert.rejects(conversationApi.putFeedback(first.message_id, feedback));
await auth.logout();
syncAuthOwner(null, session, local, true);
assert.equal(await auth.me(), null);
await assert.rejects(conversationApi.list());
await auth.login("demo@example.com", "Demo2026");
assert.equal((await conversationApi.load(conversation.id)).messages.length, 8);
await auth.logout();
console.log("Frontend clients -> HTTP API -> PostgreSQL: all assertions passed");
