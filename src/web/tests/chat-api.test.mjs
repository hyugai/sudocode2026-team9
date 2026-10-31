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
  assert.equal(calls[0].body.has("stream"), false);
  assert.equal(JSON.parse(calls[1].body).conversation_id, "same-call");
  assert.equal("stream" in JSON.parse(calls[1].body), false);
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
