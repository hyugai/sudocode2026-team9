import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { connect } from "./browser-support.mjs";

const b = await connect();
const base = process.env.BASE_URL || "http://127.0.0.1:3000";
const output = process.env.BROWSER_ARTIFACT_DIR || "/tmp/synee-voice";
await mkdir(output, { recursive: true });
const click = selector => b.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const type = (selector, value) => b.evaluate(`(() => {
  const input = document.querySelector(${JSON.stringify(selector)});
  Object.getOwnPropertyDescriptor(input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
const check = async (name, expression) => {
  assert.ok(await b.evaluate(expression), name);
  console.log("PASS", name);
};

try {
  await b.send("Page.enable");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    sessionStorage.clear();
    window.__voice = { enabled: true, mic: 0, stopped: 0, closed: 0, requests: [], sockets: [], nodes: [], denyMic: false };
    const state = window.__voice, originalFetch = window.fetch.bind(window), NativeSocket = window.WebSocket;
    window.fetch = async (input, options = {}) => {
      const url = String(input);
      if (url.endsWith('/health')) return Response.json({ status: 'ok' });
      if (url.endsWith('/api/voice/capabilities')) return Response.json({ enabled: state.enabled, requires_access_code: true });
      if (url.includes('/api/voice/sessions')) {
        state.requests.push({ url, ...options });
        if (options.method === 'POST') return Response.json({ session_id: 'test-voice', conversation_id: 'voice-conversation', owner_token: 'test-owner', connect_ticket: 'test-ticket' });
        return Response.json({ status: 'closed' });
      }
      return originalFetch(input, options);
    };
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: async () => {
      state.mic++;
      if (state.denyMic) throw new Error('Microphone bị từ chối.');
      return { getTracks: () => [{ stop() { state.stopped++; } }] };
    } });
    const node = () => ({ connect() { return this; }, disconnect() {} });
    window.AudioContext = class {
      state = 'running'; destination = {}; audioWorklet = { async addModule() {} };
      async resume() { this.state = 'running'; }
      createMediaStreamSource() { return node(); }
      createGain() { return { ...node(), gain: { value: 1 } }; }
      async close() { this.state = 'closed'; state.closed++; }
    };
    window.AudioWorkletNode = class {
      port = { postMessage: value => this.messages.push(value) }; messages = [];
      constructor(_context, name) { this.name = name; state.nodes.push(this); }
      connect() { return this; } disconnect() {}
    };
    window.WebSocket = class extends EventTarget {
      static OPEN = 1; readyState = 1; bufferedAmount = 0; sent = [];
      constructor(url, protocols) {
        super();
        if (!url.includes('/api/voice/')) return new NativeSocket(url, protocols);
        this.url = url; state.sockets.push(this);
        setTimeout(() => this.onopen?.(), 0);
      }
      send(value) {
        this.sent.push(value);
        if (typeof value === 'string' && JSON.parse(value).type === 'authenticate') {
          setTimeout(() => this.emit({ type: 'session_ready' }), 0);
        }
      }
      emit(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
      close() { this.readyState = 3; this.onclose?.(); }
    };
  ` });
  await b.send("Page.navigate", { url: base });
  await b.wait("document.querySelector('#inline-message') && !document.querySelector('.mode-toggle button:last-child').disabled");
  await type("#inline-message", "Giữ bản nháp khi dùng voice");
  await click(".mode-toggle button:last-child");
  await b.wait("document.querySelector('.voice-code-input')");
  await check("Opening Voice checks capabilities without capturing audio or creating a session", "__voice.mic === 0 && __voice.requests.length === 0 && document.querySelector('.voice-start').disabled");
  await type(".voice-code-input", "test-code");
  await click(".voice-start");
  await b.wait("document.querySelector('.voice-status')?.textContent === 'Đang lắng nghe'");
  await b.wait("document.querySelector('.voice-wave canvas') || document.querySelector('[data-wave-fallback]')");
  await check("LiveKit Wave renders with the connected listening state", "document.querySelector('.voice-wave').dataset.lkState === 'listening'");
  await check("Voice starts once with access code and socket authentication", `__voice.mic === 1 && __voice.sockets.length === 1 && __voice.requests[0].headers['X-API-Key'] === 'test-code' && JSON.parse(__voice.sockets[0].sent[0]).type === 'authenticate'`);
  await b.evaluate(`__voice.sockets[0].emit({ type: 'transcript_update', turn_id: 'one', role: 'user', text: 'Tôi cần máy lọc' });
    __voice.sockets[0].emit({ type: 'transcript_update', turn_id: 'one', role: 'agent', text: 'Em hỗ trợ' });
    __voice.sockets[0].emit({ type: 'transcript_update', turn_id: 'one', role: 'agent', text: 'Em hỗ trợ chọn máy lọc.' });`);
  await b.wait("document.querySelectorAll('.voice-line').length === 2");
  await check("Transcript updates reuse each turn bubble", "document.querySelector('.voice-line.agent').textContent.includes('Em hỗ trợ chọn máy lọc.')");
  await click(".voice-transcript summary");
  await check("Transcript expands on request without replacing the voice controls", "document.querySelector('.voice-transcript').open && !!document.querySelector('.voice-stop')");
  await click(".voice-transcript summary");
  await b.evaluate("__voice.nodes.find(n => n.name === 'telesale-capture').port.onmessage({ data: { type: 'speech_end' } })");
  await b.wait("document.querySelector('.voice-wave').dataset.lkState === 'thinking'");
  await check("Microphone speech end changes Wave to thinking", "document.querySelector('.voice-status').textContent.includes('suy nghĩ')");
  await b.evaluate("__voice.nodes.find(n => n.name === 'telesale-playback').port.onmessage({ data: { type: 'visualizer', playing: true, volume: .6, generation: 1 } })");
  await b.wait("document.querySelector('.voice-wave').dataset.lkState === 'speaking'");
  await check("Rendered playback changes Wave to speaking", "document.querySelector('.voice-status').textContent === 'Synee đang trả lời'");
  await b.screenshot(`${output}/voice-speaking.png`);
  await b.evaluate("__voice.nodes.find(n => n.name === 'telesale-playback').port.onmessage({ data: { type: 'visualizer', playing: false, volume: 0, generation: 1 } })");
  await b.wait("document.querySelector('.voice-wave').dataset.lkState === 'listening'");
  await click(".voice-actions button[aria-pressed]");
  await check("Muting sends input_audio_end", "__voice.sockets[0].sent.some(value => typeof value === 'string' && JSON.parse(value).type === 'input_audio_end')");
  await click(".voice-actions button[aria-pressed]");
  await b.evaluate("__voice.sockets[0].emit({ type: 'interrupted', generation: 2 })");
  await b.wait("document.querySelector('.voice-controls').textContent.includes('Đã dừng lời đang phát')");
  await check("Interruption flushes the playback generation", "__voice.nodes.find(n => n.name === 'telesale-playback').messages.some(m => m.type === 'flush' && m.generation === 2)");
  await b.screenshot(`${output}/voice-desktop.png`);
  await b.evaluate("window.scrollTo({ top: 1100, behavior: 'instant' })");
  await b.wait("!document.querySelector('#inline-chat')");
  await check("Switching away from inline chat keeps one live voice connection", "document.querySelectorAll('.realtime-voice').length === 1 && __voice.sockets.length === 1 && __voice.stopped === 0");
  // Native modal dialogs make background links inert. Temporarily release only
  // native modality to test a client navigation while the React voice stays mounted.
  await b.evaluate("document.querySelector('.voice-dialog').close()");
  await click(".product-card");
  await b.wait("document.querySelector('.product-detail')");
  await b.evaluate("document.querySelector('.voice-dialog').showModal()");
  await check("Client navigation preserves the voice dialog and microphone", "!!document.querySelector('dialog[open] .voice-stop') && __voice.stopped === 0 && __voice.sockets.length === 1");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
  await check("Voice dialog fits a 320px viewport", "document.documentElement.scrollWidth <= 320 && document.querySelector('dialog').scrollWidth <= document.querySelector('dialog').clientWidth");
  await check("Mobile keeps microphone and end-call controls inside the viewport", "[...document.querySelectorAll('.voice-actions button')].every(button => { const r = button.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })");
  await b.screenshot(`${output}/voice-mobile.png`);
  await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await b.wait("document.querySelector('[data-wave-fallback]') && !document.querySelector('.voice-wave canvas')");
  await check("Reduced motion keeps a static Wave without a running WebGL canvas", "!!document.querySelector('.voice-wave[data-lk-state=listening]')");
  await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await b.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await b.wait("!document.querySelector('dialog[open]') && __voice.stopped === 1 && __voice.requests.some(r => r.method === 'DELETE')");
  await check("Closing Voice releases microphone, context, socket and backend session", "__voice.closed === 1 && __voice.sockets[0].readyState === 3 && __voice.requests.find(r => r.method === 'DELETE').headers.Authorization === 'Bearer test-owner'");
  await b.wait("document.querySelector('.pdp-ask') && !document.querySelector('.pdp-ask').disabled");
  await click(".pdp-ask");
  await b.wait("document.querySelector('#floating-message')");
  await check("Text draft remains available after Voice closes", "document.querySelector('#floating-message').value === 'Giữ bản nháp khi dùng voice' && !document.querySelector('#floating-message').disabled");
  await click(".mode-toggle button:last-child");
  await b.wait("document.querySelector('.voice-code-input')");
  await type(".voice-code-input", "test-code");
  await b.evaluate("__voice.denyMic = true");
  await click(".voice-start");
  await b.wait("document.querySelector('.realtime-voice .error')");
  await check("Denied microphone shows a recoverable error without creating another session", "document.querySelector('.error').textContent.includes('bị từ chối') && __voice.requests.filter(r => r.method === 'POST').length === 1 && !document.querySelector('.voice-start').disabled");
  await click("dialog[open] .dialog-header button");
  await b.evaluate("__voice.enabled = false");
  await click(".mode-toggle button:last-child");
  await b.wait("document.querySelector('.voice-status')?.textContent === 'Voice chưa sẵn sàng'");
  await check("Unavailable voice leaves chat and audio upload usable", "document.querySelector('.voice-start').disabled && !!document.querySelector('.upload-button')");
  await click("dialog[open] .dialog-header button");
  await b.evaluate(`__voice.enabled = true; __voice.beforeFallbackMic = __voice.mic;
    const originalContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {
      return type === 'webgl' || type === 'experimental-webgl' ? null : originalContext.call(this, type, ...args);
    };`);
  await click(".mode-toggle button:last-child");
  await b.wait("document.querySelector('[data-wave-fallback]') && document.querySelector('.voice-code-input')");
  await check("Unavailable WebGL falls back without starting the microphone or losing call controls", "__voice.mic === __voice.beforeFallbackMic && !!document.querySelector('.voice-start')");
} catch (error) {
  console.error(await b.evaluate("({ url: location.href, dialog: !!document.querySelector('dialog[open]'), text: document.body.innerText.slice(0, 1800) })"));
  throw error;
} finally {
  await b.close();
}
