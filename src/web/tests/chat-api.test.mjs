import assert from "node:assert/strict";
import test from "node:test";
import { ChatApiError, createChatClient } from "../utils/chat-api.ts";

const turn = () => ({
  conversationId: "same-call", message: "xin chào", customerPhone: "0901234567",
  audioFile: new File(["speech"], "recording.wav", { type: "audio/wav" }),
});
const success = () => Response.json({ response: "Xin chào bạn", transcript: "xin chào" });

test("rapid submits produce one upload and unlock after it finishes", async () => {
  let finish;
  let count = 0;
  const client = createChatClient("http://backend", () => {
    count++;
    return new Promise((resolve) => { finish = resolve; });
  });
  const first = client.send(turn());
  assert.equal(client.isSending, true);
  assert.deepEqual(await Promise.all(Array.from({ length: 20 }, () => client.send(turn()))), Array(20).fill(null));
  assert.equal(count, 1);
  finish(success());
  await first;
  assert.equal(client.isSending, false);
  const next = client.send(turn());
  assert.equal(count, 2);
  finish(success());
  await next;
});

test("voice and text send the same conversation and correct body types", async () => {
  const calls = [];
  const client = createChatClient("http://backend", async (url, options) => {
    calls.push({ url, ...options });
    return success();
  });
  const voice = turn();
  await client.send(voice);
  await client.send({ ...voice, audioFile: null });
  assert.equal(calls[0].url, "http://backend/api/chat/audio");
  assert.equal(calls[0].headers, undefined); // Browser supplies the multipart boundary.
  assert.equal(calls[0].body.get("file"), voice.audioFile);
  assert.equal(calls[0].body.get("conversation_id"), "same-call");
  assert.equal(JSON.parse(calls[1].body).conversation_id, "same-call");
});

test("failed upload keeps the file, releases the lock, and never retries automatically", async () => {
  let count = 0;
  const request = turn();
  const client = createChatClient("http://backend", async () => {
    if (++count === 1) throw new TypeError("Failed to fetch");
    return success();
  });
  await assert.rejects(client.send(request), (error) => error instanceof ChatApiError && error.connectionLost);
  assert.equal(count, 1);
  assert.equal(request.audioFile.name, "recording.wav");
  assert.equal(client.isSending, false);
  await client.send(request);
  assert.equal(count, 2);
});

test("429 respects provider cooldown before allowing another request", async () => {
  let clock = 1000;
  let count = 0;
  const client = createChatClient("http://backend", async () => {
    if (++count === 1) return Response.json({ detail: "Chờ 8 giây", retry_after_seconds: 8 }, { status: 429 });
    return success();
  }, () => clock);
  await assert.rejects(client.send(turn()), (error) => error.retryAfterSeconds === 8);
  await assert.rejects(client.send(turn()), ChatApiError);
  assert.equal(count, 1);
  clock += 8000;
  await client.send(turn());
  assert.equal(count, 2);
});

test("a successful turn can report cooldown from optional memory summarization", async () => {
  const client = createChatClient("http://backend", async () => Response.json({ response: "Xin chào", retry_after_seconds: 5 }));
  await client.send(turn());
  assert.equal(client.retryAfterSeconds, 5);
  await assert.rejects(client.send(turn()), ChatApiError);
});

test("non-JSON server errors become a readable message", async () => {
  const client = createChatClient("http://backend", async () => new Response("Internal Server Error", { status: 500 }));
  await assert.rejects(client.send(turn()), /HTTP 500/);
  assert.equal(client.isSending, false);
});

test("health checks distinguish ready, starting, and disconnected backends", async () => {
  const signal = new AbortController().signal;
  for (const status of [200, 503]) {
    const client = createChatClient("http://backend", async () => new Response("", { status }));
    assert.equal(await client.isReady(signal), status === 200);
  }
  const offline = createChatClient("http://backend", async () => { throw new TypeError("Failed to fetch"); });
  assert.equal(await offline.isReady(signal), false);
});

test("SSE delivers progress before completion and handles fragmented UTF-8", async () => {
  const encoder = new TextEncoder();
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  const client = createChatClient("http://backend", async () => new Response(body, { headers: { "Content-Type": "text/event-stream" } }));
  const progress = [];
  const pending = client.send({ ...turn(), audioFile: null }, (event) => progress.push(event));
  const chunk = encoder.encode('data: {"type":"delta","text":"Xin chào chị. "}\n\n');
  for (const byte of chunk) controller.enqueue(new Uint8Array([byte]));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(progress[0].text, "Xin chào chị. ");
  assert.equal(client.isSending, true);
  controller.enqueue(encoder.encode('data: {"type":"complete","response":"Xin chào chị. Em hỗ trợ nhé."}\n\n'));
  controller.close();
  assert.equal((await pending).response, "Xin chào chị. Em hỗ trợ nhé.");
  assert.equal(client.isSending, false);
});

test("an interrupted SSE turn is reported and is never replayed automatically", async () => {
  let calls = 0;
  const client = createChatClient("http://backend", async () => {
    calls++;
    return new Response('data: {"type":"delta","text":"Đã nhận."}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  });
  await assert.rejects(client.send(turn()), (error) => error.connectionLost);
  assert.equal(calls, 1);
  assert.equal(client.isSending, false);
});

test("an SSE backend error keeps cooldown and rejects the turn", async () => {
  const client = createChatClient("http://backend", async () => new Response('data: {"type":"error","detail":"Chờ quota","retry_after_seconds":7}\n\n', { headers: { "Content-Type": "text/event-stream" } }));
  await assert.rejects(client.send(turn()), (error) => error.retryAfterSeconds === 7);
});

test("coalesced SSE events let the UI paint before processing completion", async () => {
  const frames = 'data: {"type":"delta","text":"Dạ em "}\n\n'
    + 'data: {"type":"delta","text":"hỗ trợ nhé."}\n\n'
    + 'data: {"type":"complete","response":"Dạ em hỗ trợ nhé."}\n\n';
  let paint;
  let progress = "";
  const client = createChatClient("http://backend", async () => new Response(frames, { headers: { "Content-Type":"text/event-stream" } }));
  const pending = client.send(turn(), async (event) => {
    progress += event.text;
    await new Promise((resolve) => { paint = resolve; });
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(progress, "Dạ em ");
  assert.equal(client.isSending, true);
  paint();
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(progress, "Dạ em hỗ trợ nhé.");
  assert.equal(client.isSending, true);
  paint();
  assert.equal((await pending).response, "Dạ em hỗ trợ nhé.");
});
