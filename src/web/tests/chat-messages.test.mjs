import assert from "node:assert/strict";
import test from "node:test";
import { upsertChatTurn } from "../utils/chat-messages.ts";

test("waiting and complete response keep one assistant bubble per turn", () => {
  const history = [{ role: "agent", text: "Xin chào" }];
  let messages = upsertChatTurn(history, "answer-1", "Mua máy lạnh", "");
  assert.equal(messages.length, 3);
  assert.equal(messages.filter((message) => message.id === "answer-1").length, 1);
  messages = upsertChatTurn(messages, "answer-1", "mua máy lạnh", "");
  messages = upsertChatTurn(messages, "answer-1", "mua máy lạnh", "Dạ em hỗ trợ nhé.");
  messages = upsertChatTurn(messages, "answer-1", "mua máy lạnh", "Dạ em hỗ trợ nhé.");
  assert.equal(messages.length, 3);
  assert.equal(messages.filter((message) => message.role === "agent").length, 2); // Greeting + one answer.
  assert.equal(history.length, 1);
});
