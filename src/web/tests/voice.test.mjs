import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { voiceSocketUrl } from "../utils/voice-api.ts";
import { VoiceAudio } from "../utils/voice-audio.ts";

function processor(name, rate = 48000) {
  let Class;
  const messages = [];
  vm.runInNewContext(readFileSync(new URL("../public/audio/" + name + ".js", import.meta.url), "utf8"), {
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage: (x) => messages.push(x) }; } },
    registerProcessor: (_name, value) => { Class = value; },
    sampleRate: rate, Float32Array, Int16Array, Math,
  });
  return { instance: new Class(), messages };
}

test("voice socket preserves deployment prefix and never copies query credentials", () => {
  assert.equal(voiceSocketUrl("https://api.example.com/backend?secret=value", "abc"),
    "wss://api.example.com/backend/api/voice/sessions/abc/stream");
  assert.throws(() => voiceSocketUrl("javascript:alert(1)", "abc"));
});

test("visualizer volume follows actual resampled output and clears when playback drains or is flushed", () => {
  const { instance, messages } = processor("voice-playback-worklet", 48000);
  instance.port.onmessage({ data: { type: "audio", buffer: new Int16Array(24000).fill(8192).buffer, generation: 1, turnId: "visual" } });
  assert.equal(messages.filter(m => m.type === "visualizer").length, 0);
  const out = new Float32Array(128);
  instance.process([], [[out]]);
  let visual = messages.filter(m => m.type === "visualizer");
  assert.equal(visual[0].playing, true);
  assert.equal(visual[0].volume, 0.5);
  for (let i = 1; i < 400; i++) instance.process([], [[out]]);
  visual = messages.filter(m => m.type === "visualizer");
  assert.deepEqual({ ...visual.at(-1) }, { type: "visualizer", playing: false, generation: 1, volume: 0 });
  assert.ok(visual.length <= 23, "telemetry stays near 20 Hz, not one event per audio quantum");
  instance.port.onmessage({ data: { type: "audio", buffer: new Int16Array(24000).fill(8192).buffer, generation: 2, turnId: "interrupt" } });
  instance.process([], [[out]]);
  instance.port.onmessage({ data: { type: "flush", generation: 3 } });
  assert.deepEqual({ ...messages.at(-1) }, { type: "visualizer", playing: false, generation: 3, volume: 0 });
});

test("microphone VAD reports one speech end after silence for the thinking animation", () => {
  const { instance, messages } = processor("voice-capture-worklet", 48000);
  for (let i = 0; i < 40; i++) instance.process([[new Float32Array(128).fill(.5)]]);
  for (let i = 0; i < 300; i++) instance.process([[new Float32Array(128)]]);
  assert.equal(messages.filter(m => m.type === "speech_start").length, 1);
  assert.equal(messages.filter(m => m.type === "speech_end").length, 1);
});

test("one second of 48kHz microphone produces 50 real 20ms PCM16 frames", () => {
  const { instance, messages } = processor("voice-capture-worklet");
  for (let i = 0; i < 375; i++) instance.process([[new Float32Array(128).fill(.5)]]);
  const frames = messages.filter((message) => message.type === "pcm");
  assert.equal(frames.length, 50);
  assert.equal(frames[0].buffer.byteLength, 640);
  assert.ok(new Int16Array(frames[0].buffer).every((sample) => sample === 16384));
});

test("playback flush stops old audio and stale generations cannot refill it", () => {
  const { instance } = processor("voice-playback-worklet");
  const audio = new Int16Array(1200).fill(16000).buffer;
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 1, turnId: "a" } });
  const out = new Float32Array(128);
  instance.process([], [[out]]);
  assert.ok(out.some((value) => value > 0));
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 2, turnId: "b" } });
  instance.port.onmessage({ data: { type: "flush" } });
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 1, turnId: "a" } });
  instance.process([], [[out]]);
  assert.ok(out.every((value) => value === 0));
});

test("a 12-second response arriving in a burst plays fully without overflow", () => {
  const { instance, messages } = processor("voice-playback-worklet", 24000);
  const source = new Int16Array(24000 * 12).fill(16000);
  source[0] = 8000;
  source[source.length - 1] = 24000;
  for (let offset = 0; offset < source.length; offset += 2400) {
    instance.port.onmessage({ data: { type: "audio", buffer: source.slice(offset, offset + 2400).buffer,
      generation: 1, turnId: "burst" } });
  }
  assert.equal(messages.filter((message) => message.type === "overflow").length, 0);
  const out = new Float32Array(128);
  for (let offset = 0; offset < source.length; offset += out.length) {
    instance.process([], [[out]]);
    for (let index = 0; index < out.length; index++) {
      assert.equal(out[index], source[offset + index] / 32768);
    }
  }
  instance.process([], [[out]]);
  assert.ok(out.every((value) => value === 0));
});

test("24kHz audio plays at its original duration on 44.1kHz and 48kHz devices", () => {
  for (const rate of [44100, 48000]) {
    const { instance } = processor("voice-playback-worklet", rate);
    instance.port.onmessage({ data: { type: "audio", buffer: new Int16Array(24000).fill(16000).buffer,
      generation: 1, turnId: "resample" } });
    const out = new Float32Array(128);
    let audibleFrames = 0;
    for (let offset = 0; offset < rate + out.length; offset += out.length) {
      instance.process([], [[out]]);
      audibleFrames += out.filter((value) => value > 0).length;
    }
    assert.ok(Math.abs(audibleFrames - rate) <= 1);
  }
});

test("growing a partly played buffer preserves sample order and fractional resampling", () => {
  const rate = 44100;
  const source = Int16Array.from({ length: 24000 * 10 }, (_, index) =>
    Math.round(Math.sin(index * 2 * Math.PI * 440 / 24000) * 16000));
  const baseline = processor("voice-playback-worklet", rate).instance;
  const streaming = processor("voice-playback-worklet", rate).instance;
  const enqueue = (target, samples) => target.port.onmessage({ data: {
    type: "audio", buffer: samples.buffer, generation: 1, turnId: "grow" } });
  enqueue(baseline, source);
  enqueue(streaming, source.slice(0, 36000));
  const expected = new Float32Array(128);
  const actual = new Float32Array(128);
  let maxError = 0;
  for (let offset = 0; offset < rate * 10; offset += actual.length) {
    if (offset === 128 * 127) enqueue(streaming, source.slice(36000));
    baseline.process([], [[expected]]);
    streaming.process([], [[actual]]);
    for (let index = 0; index < actual.length; index++) {
      maxError = Math.max(maxError, Math.abs(expected[index] - actual[index]));
    }
  }
  assert.ok(maxError < 1e-6, `sample error after growth: ${maxError}`);
});

test("an interruption rejects late audio even before the next generation arrives", () => {
  const { instance } = processor("voice-playback-worklet");
  const audio = new Int16Array(1200).fill(16000).buffer;
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 1, turnId: "old" } });
  instance.port.onmessage({ data: { type: "flush", generation: 2 } });
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 1, turnId: "old" } });
  const out = new Float32Array(128);
  instance.process([], [[out]]);
  assert.ok(out.every((value) => value === 0));
  instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 3, turnId: "new" } });
  instance.process([], [[out]]);
  assert.ok(out.some((value) => value > 0));
});

test("excessive audio stays bounded and reports overflow only once", () => {
  const { instance, messages } = processor("voice-playback-worklet");
  const audio = new Int16Array(24000).buffer;
  for (let index = 0; index < 90; index++) {
    instance.port.onmessage({ data: { type: "audio", buffer: audio, generation: 1, turnId: "limit" } });
  }
  assert.equal(messages.filter((message) => message.type === "overflow").length, 1);
  assert.ok(instance.write - instance.read <= 24000 * 60);
});

test("audio suspended by the microphone prompt resumes before the voice session starts", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const savedWindow = globalThis.window;
  const savedContext = globalThis.AudioContext;
  const savedNode = globalThis.AudioWorkletNode;
  const nodes = [];
  const contexts = [];
  let stopped = 0;
  let resumes = 0;
  const errors = [];
  const node = () => ({ connect() { return this; }, disconnect() {} });
  globalThis.AudioContext = class {
    state = "suspended";
    destination = {};
    audioWorklet = { async addModule() {} };
    constructor() { contexts.push(this); }
    async resume() { resumes++; this.state = "running"; }
    createMediaStreamSource() { return node(); }
    createGain() { return { ...node(), gain: { value: 1 } }; }
    async close() { this.state = "closed"; }
  };
  globalThis.AudioWorkletNode = class {
    port = { postMessage() {} };
    constructor(_context, name, options) { this.name = name; this.options = options; nodes.push(this); }
    connect() { return this; }
    disconnect() {}
  };
  globalThis.window = { AudioContext: globalThis.AudioContext };
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
    mediaDevices: { async getUserMedia() {
      contexts[0].state = "suspended";
      return { getTracks: () => [{ stop() { stopped++; } }] };
    } },
  } });
  const audio = new VoiceAudio();
  try {
    await audio.start(() => {}, () => {}, () => {}, (message) => errors.push(message));
    const context = contexts[0];
    assert.equal(context.state, "running");
    assert.equal(resumes, 2);
    const playback = nodes.find((item) => item.name === "telesale-playback");
    assert.equal(playback.options.numberOfInputs, 0);
    assert.deepEqual(playback.options.outputChannelCount, [1]);
    context.state = "suspended";
    context.onstatechange?.();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(context.state, "running");
    assert.equal(resumes, 3);
    assert.deepEqual(errors, []);
    context.resume = async () => { throw new Error("device unavailable"); };
    context.state = "suspended";
    context.onstatechange?.();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(errors.length, 1);
    assert.match(errors[0], /tạm dừng âm thanh/);
    context.onstatechange?.();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(errors.length, 1);
    await audio.close();
    assert.equal(context.onstatechange, null);
    assert.equal(stopped, 1);
  } finally {
    await audio.close();
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
    globalThis.AudioContext = savedContext;
    globalThis.AudioWorkletNode = savedNode;
    globalThis.window = savedWindow;
  }
});

test("microphone permission resolving after mode switch releases the late stream", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const savedContext = globalThis.AudioContext;
  let resolveMic;
  let stopped = 0;
  globalThis.window = { AudioContext: true };
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
    mediaDevices: { getUserMedia: () => new Promise((resolve) => { resolveMic = resolve; }) },
  } });
  globalThis.AudioContext = class {
    state = "running";
    async resume() {}
    async close() { this.state = "closed"; }
  };
  try {
    const audio = new VoiceAudio();
    const start = audio.start(() => {}, () => {}, () => {}, () => {});
    await Promise.resolve();
    await audio.close();
    resolveMic({ getTracks: () => [{ stop: () => stopped++ }] });
    await start;
    assert.equal(stopped, 1);
    await audio.close();
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
    globalThis.AudioContext = savedContext;
    delete globalThis.window;
  }
});
