import assert from "node:assert/strict";
import test from "node:test";
import { createChatClient } from "../utils/chat-api.ts";

const turn = { conversationId: "demo", message: "Hello", audioFile: null, customerPhone: "" };
const encode = value => new TextEncoder().encode(value);
const event = (type, data) => `event: ${type}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;
const response = stream => new Response(stream, { headers: { "Content-Type": "text/event-stream" } });

test("stream delivers split UTF-8 drafts before the final guarded response and DB IDs", async () => {
  let controller;
  const stream = new ReadableStream({ start(value) { controller = value; } });
  const drafts = [];
  const stages = [];
  let headers;
  const client = createChatClient("", async (_url, options) => { headers = options.headers; return response(stream); }, Date.now, true);
  const pending = client.send(turn, text => drafts.push(text), stage => stages.push(stage));
  controller.enqueue(encode(': keepalive\r\n\r\n' + event("status", { stage: "processing" })));
  controller.enqueue(encode(event("status", { stage: "analyzing" }) + event("status", { stage: "unknown-internal-step" })));
  const bytes = encode(event("text", { text: "Tiếng Việt" }));
  // Split inside every multibyte character and SSE delimiter.
  for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(drafts, ["Tiếng Việt"]);
  assert.deepEqual(stages, ["processing", "analyzing"]);
  assert.equal(client.isSending, true);
  assert.equal(headers.Accept, "text/event-stream");
  assert.equal(headers["X-Conversation-Mode"], "account");
  controller.enqueue(encode(event("done", { response: "Verified", message_id: "db-id", call_brief: { summary: "Brief" } })));
  controller.close();
  const final = await pending;
  assert.equal(final.response, "Verified");
  assert.equal(final.message_id, "db-id");
  assert.equal(final.callBrief.summary, "Brief");
  assert.equal(client.isSending, false);
});

test("incomplete stream never treats a draft as saved and never replays the POST", async () => {
  let calls = 0;
  const client = createChatClient("", async () => {
    calls++;
    return response(new ReadableStream({ start(controller) {
      controller.enqueue(encode(event("text", { text: "Draft only" })));
      controller.close();
    } }));
  });
  await assert.rejects(client.send(turn, () => {}), /lịch sử/);
  assert.equal(client.isSending, false);
  assert.equal(calls, 1);
});

test("SSE errors preserve the retry cooldown and release the sending lock", async () => {
  const client = createChatClient("", async () => response(new ReadableStream({ start(controller) {
    controller.enqueue(encode(event("error", { status: 429, detail: "Wait", retry_after_seconds: 10 })));
    controller.close();
  } })), () => 1000);
  await assert.rejects(client.send(turn, () => {}), error => error.retryAfterSeconds === 10);
  assert.equal(client.retryAfterSeconds, 10);
  assert.equal(client.isSending, false);
});
