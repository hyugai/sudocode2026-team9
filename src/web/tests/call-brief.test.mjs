import assert from "node:assert/strict";
import test from "node:test";
import { readCallBrief } from "../utils/call-brief.ts";
import { createChatClient } from "../utils/chat-api.ts";

const brief = { summary: " Tìm máy lọc cho phòng ngủ. ", needs: ["Yên tĩnh", " Yên tĩnh ", "Vừa ngân sách"], objections: ["Chi phí màng lọc"], unresolved_issues: ["Xác nhận diện tích phòng"] };
const turn = { conversationId: "same-call", message: "Tư vấn máy lọc", audioFile: null, customerPhone: "" };

test("Call brief selects only display fields and does not retain CRM or memory", () => {
  const source = { ...brief, customer_id: "private", verified_customer_data: { address: "private" }, remembered_preferences: { facts: "private" } };
  assert.deepEqual(readCallBrief(source), { summary: "Tìm máy lọc cho phòng ngủ.", needs: ["Yên tĩnh", "Vừa ngân sách"], objections: ["Chi phí màng lọc"], unresolvedIssues: ["Xác nhận diện tích phòng"] });
  assert.equal(source.summary, brief.summary);
});

test("Missing and malformed call briefs stay empty while valid fields are bounded", () => {
  for (const value of [null, undefined, [], 1, "text", {}, { summary: 3, needs: [{}], objections: "bad" }]) assert.equal(readCallBrief(value), null);
  const value = readCallBrief({ summary: "x".repeat(5000), needs: Array.from({ length: 20 }, (_, index) => `${index}-` + "n".repeat(2000)) });
  assert.equal(value.summary.length, 4000);
  assert.equal(value.needs.length, 12);
  assert.ok(value.needs.every(item => item.length === 1000));
});

test("Text and offline audio receive the public pipeline call brief without debug", async () => {
  for (const audioFile of [null, new File(["speech"], "recording.wav", { type: "audio/wav" })]) {
    const client = createChatClient("http://backend", async () => Response.json({ response: "Mình sẽ tư vấn.", transcript: "Tư vấn máy lọc", call_brief: brief }));
    const response = await client.send({ ...turn, audioFile });
    assert.deepEqual(response.callBrief, readCallBrief(brief));
    assert.equal(response.debug, undefined);
  }
});

test("A public brief takes precedence and unavailable data never invalidates a chat reply", async () => {
  for (const call_brief of [null, { needs: [null, {}] }, { summary: "Bản hiển thị được cấp quyền" }]) {
    const client = createChatClient("http://backend", async () => Response.json({ response: "Phản hồi hợp lệ", call_brief }));
    const response = await client.send(turn);
    assert.equal(response.response, "Phản hồi hợp lệ");
    assert.deepEqual(response.callBrief, readCallBrief(call_brief));
  }
  const client = createChatClient("http://backend", async () => Response.json({ response: "OK", call_brief: { summary: "Bản công khai" }, debug: { call_brief: brief } }));
  assert.equal((await client.send(turn)).callBrief.summary, "Bản công khai");
});
