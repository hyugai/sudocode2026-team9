import test from "node:test";
import assert from "node:assert/strict";
import { idleVisualizer, updateVoiceVisualizer } from "../utils/voice-visualizer.ts";

test("visualizer follows connection, input completion, rendered playback and interruption", () => {
  let value = updateVoiceVisualizer(idleVisualizer, { type: "session_ready" });
  assert.equal(value.state, "listening");
  value = updateVoiceVisualizer(value, { type: "agent_state", state: "thinking" });
  assert.equal(value.state, "thinking");
  value = updateVoiceVisualizer(value, { type: "playback", playing: true, volume: 0.6 });
  assert.deepEqual(value, { state: "speaking", volume: 0.6 });
  // A provider transcript or memory receipt can precede the end of buffered audio.
  for (const event of [
    { type: "transcript_update", role: "agent", text: "Xin chào" },
    { type: "transcript_update", role: "user", finished: true },
    { type: "memory_committed" },
    { type: "agent_state", state: "thinking" },
  ]) assert.equal(updateVoiceVisualizer(value, event), value);
  assert.deepEqual(updateVoiceVisualizer(value, { type: "playback", playing: false, volume: 0.6 }), { state: "listening", volume: 0 });
  assert.deepEqual(updateVoiceVisualizer(value, { type: "interrupted" }), { state: "listening", volume: 0 });
  assert.equal(updateVoiceVisualizer(value, { type: "connection", status: "reconnecting" }).state, "connecting");
  assert.equal(updateVoiceVisualizer(value, { type: "error" }), idleVisualizer);
  assert.equal(updateVoiceVisualizer(value, { type: "disconnected" }), idleVisualizer);
});

test("volume is bounded and malformed values never reach the shader", () => {
  for (const [volume, expected] of [[-1, 0], [2, 1], [NaN, 0], [Infinity, 0], [undefined, 0]]) {
    assert.equal(updateVoiceVisualizer(idleVisualizer, { type: "playback", playing: true, volume }).volume, expected);
  }
});
