// Run against Next.js and a local Chromium CDP session. All chat/voice services
// and microphone devices are mocked; no customer data or live AI calls are used.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { connect } from "./browser-support.mjs";

const b = await connect();
const base = process.env.BASE_URL || "http://127.0.0.1:3000";
const output = process.env.BROWSER_ARTIFACT_DIR || fileURLToPath(new URL("../../../outputs/debug/streaming-ui/ai-chat/", import.meta.url));
await mkdir(output, { recursive: true });
const click = selector => b.evaluate(`(() => { const control = document.querySelector(${JSON.stringify(selector)}); control.focus(); control.click(); })()`);
const type = (selector, value) => b.evaluate(`(() => {
  const n = document.querySelector(${JSON.stringify(selector)});
  Object.getOwnPropertyDescriptor(n.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(n, ${JSON.stringify(value)});
  n.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
const check = async (name, expression) => { assert.ok(await b.evaluate(expression), name); console.log("PASS", name); };
const mode = name => click(`.ai-mode-bar button:nth-child(${name === "text" ? 1 : 2})`);
const openDashboard = async () => {
  await click(".ai-exit-link");
  await b.wait("location.pathname === '/' && !!document.querySelector('.hero')");
  // Normalize restored scroll before interacting with the dashboard launcher.
  await b.evaluate("window.scrollTo({ top: 0, behavior: 'instant' })");
  await b.wait("!!document.querySelector('#inline-message')");
};
const upload = (size = 8) => b.evaluate(`(() => {
  const file = new File([new Uint8Array(${size})], 'ghi-am-nhu-cau-rat-dai.wav', { type: 'audio/wav' });
  const transfer = new DataTransfer(); transfer.items.add(file);
  const input = document.querySelector('input[type=file]'); input.files = transfer.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
})()`);
const submit = () => b.evaluate("document.querySelector('.ai-composer').requestSubmit()");
const escape = () => b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });

try {
  await b.send("Page.enable");
  await b.send("Page.bringToFront");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    if (!sessionStorage.getItem('ai-chat-test-seeded')) {
      sessionStorage.clear();
      sessionStorage.setItem('ai-chat-test-seeded', '1');
      sessionStorage.setItem('synee.guest.conversation.v1', JSON.stringify({ version: 1,
        messages: [{ role: 'agent', text: 'Chào bạn, mình là Synee AI.' }], input: '', sessionId: '',
        customerPhone: '0901234567', voicePreview: false, consultation: null }));
    }
    window.__test = { calls: [], ready: true, apiMode: 'ok', voiceEnabled: true, mic: 0, stopped: 0, sockets: [], voiceRequests: [], nodes: [] };
    const state = window.__test, originalFetch = window.fetch.bind(window), NativeSocket = window.WebSocket;
    window.fetch = async (input, options = {}) => {
      const url = String(input);
      if (url.endsWith('/health')) return Response.json({}, { status: state.ready ? 200 : 503 });
      if (/\\/api\\/chat(?:\\/audio)?$/.test(url)) {
        const audio = options.body instanceof FormData;
        const data = audio ? Object.fromEntries(options.body.entries()) : JSON.parse(options.body);
        state.calls.push({ url, conversationId: data.conversation_id, phone: data.customer_phone, message: data.message, file: data.file?.name });
        await new Promise(r => setTimeout(r, 150));
        if (state.apiMode === 'error') return Response.json({ detail: 'Không xử lý được. Hãy thử lại.' }, { status: 502 });
        if (state.apiMode === 'limit') return Response.json({ retry_after_seconds: 2 }, { status: 429 });
        return Response.json({ response: 'Synee đã ghi nhận nhu cầu của bạn.', ...(audio ? { transcript: 'Tôi cần tai nghe pin lâu.' } : { normalized_message: data.message }) });
      }
      if (/\\/api\\/sessions\\//.test(url) && options.method === 'DELETE') return Response.json({ status: 'cleared', conversation_id: decodeURIComponent(url.split('/').pop()) });
      if (url.endsWith('/api/voice/capabilities')) return Response.json({ enabled: state.voiceEnabled, requires_access_code: false });
      if (url.includes('/api/voice/sessions')) {
        state.voiceRequests.push(options);
        return Response.json(options.method === 'POST' ? { session_id: 'test-voice', conversation_id: 'voice-test', owner_token: 'test-owner', connect_ticket: 'test-ticket' } : { status: 'closed' });
      }
      return originalFetch(input, options);
    };
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: async () => {
      state.mic++;
      if (state.denyMic) throw new Error('Microphone bị từ chối trong kiểm thử.');
      return { getTracks: () => [{ stop() { state.stopped++; } }] };
    } });
    const node = () => ({ connect() { return this; }, disconnect() {} });
    window.AudioContext = class {
      state = 'running'; destination = {}; audioWorklet = { async addModule() {} };
      async resume() {} createMediaStreamSource() { return node(); }
      createGain() { return { ...node(), gain: { value: 1 } }; }
      async close() { this.state = 'closed'; }
    };
    window.AudioWorkletNode = class {
      port = { postMessage: value => this.messages.push(value) }; messages = [];
      constructor(_context, name) { this.name = name; state.nodes.push(this); }
      connect() { return this; } disconnect() {}
    };
    window.WebSocket = class extends EventTarget {
      static OPEN = 1; readyState = 1; bufferedAmount = 0; sent = [];
      constructor(url, protocols) {
        super(); if (!url.includes('/api/voice/')) return new NativeSocket(url, protocols);
        state.sockets.push(this); setTimeout(() => this.onopen?.(), 0);
      }
      send(value) { this.sent.push(value); if (typeof value === 'string' && JSON.parse(value).type === 'authenticate') setTimeout(() => this.emit({ type: 'session_ready' }), 0); }
      emit(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
      close() { this.readyState = 3; this.onclose?.(); }
    };
  ` });
  await b.send("Page.navigate", { url: base });
  await b.wait("document.querySelector('#inline-message') && !document.querySelector('.mode-toggle button:last-child').disabled");
  await check("Dashboard exposes only Chat and Voice", "JSON.stringify([...document.querySelectorAll('.mode-toggle button')].map(button => button.textContent)) === JSON.stringify(['Chat', 'Voice'])");
  await b.screenshot(`${output}/dashboard-entry-desktop.png`);
  await type("#inline-message", "Tìm tai nghe dưới 3 triệu");
  await b.evaluate("document.querySelector('.composer').requestSubmit(); document.querySelector('.composer')?.requestSubmit()");
  await b.wait("location.pathname === '/ai-chat' && document.querySelectorAll('.ai-message').length === 3");
  await check("Dashboard send opens the new workspace and sends exactly one real API request", "__test.calls.length === 1 && !document.querySelector('.site-header') && !document.querySelector('.product-grid')");
  await check("Customer identity is preserved across navigation", "__test.calls[0].phone === '0901234567'");
  await check("Workspace exposes only Chat and Voice", "JSON.stringify([...document.querySelectorAll('.ai-mode-bar button')].map(button => button.textContent)) === JSON.stringify(['Chat', 'Voice'])");
  await check("The workspace omits the session note, ready heading and empty-input instruction", "!document.querySelector('.ai-session-note') && !document.querySelector('.ai-topbar [role=status]') && !document.body.innerText.includes('Synee đã sẵn sàng') && !document.body.innerText.includes('Cuộc trò chuyện cùng Synee') && document.querySelector('#ai-send-status').textContent === '' && getComputedStyle(document.querySelector('#ai-send-status')).display === 'none'");
  await b.evaluate("window.__conversationId = __test.calls[0].conversationId");
  await type("#ai-message", "Giữ bản nháp khi chuyển chế độ");
  await upload();
  await b.wait("!!document.querySelector('audio')");
  await check("Audio upload stays in Chat, previews the file and preserves the text draft", "document.querySelector('#ai-message').value === 'Giữ bản nháp khi chuyển chế độ' && document.querySelector('.audio-preview').textContent.includes('ghi-am') && document.querySelector('.ai-mode-bar button:first-child').getAttribute('aria-pressed') === 'true' && document.querySelectorAll('.ai-mode-bar button').length === 2");
  await b.screenshot(`${output}/chat-audio-desktop.png`);
  await b.evaluate("__test.apiMode = 'error'");
  await submit();
  await b.wait("document.querySelector('[role=alert]')?.textContent.includes('Không xử lý')");
  await check("Failed upload preserves file and draft without retrying", "__test.calls.length === 2 && !!document.querySelector('audio') && document.querySelector('#ai-message').value.includes('Giữ bản nháp')");
  await b.evaluate("__test.apiMode = 'ok'");
  await submit();
  await b.wait("document.querySelectorAll('.ai-message').length === 5");
  await check("Chat audio uses the ASR endpoint, renders its transcript and shares the text conversation ID", "__test.calls.every(call => call.conversationId === __conversationId) && __test.calls[2].url.endsWith('/api/chat/audio') && __test.calls[2].file.endsWith('.wav') && [...document.querySelectorAll('.ai-bubble')].some(bubble => bubble.textContent === 'Tôi cần tai nghe pin lâu.') && document.querySelector('#ai-message').value.includes('Giữ bản nháp') && !document.querySelector('audio')");
  await mode("text");
  await b.evaluate("__test.apiMode = 'limit'");
  await submit();
  await b.wait("document.querySelector('#ai-send-status').textContent.includes('giây')");
  await check("Rate limits disable sending and retain input", "document.querySelector('.ai-send').disabled && document.querySelector('#ai-message').value.includes('Giữ bản nháp')");
  await b.evaluate("__test.apiMode = 'ok'");
  await b.wait("!document.querySelector('.ai-send').disabled");
  await check("Cooldown expiry does not resend automatically", "__test.calls.length === 4");
  await b.screenshot(`${output}/chat-desktop.png`);
  await type("#ai-message", "Nội dung dài " + "0901234567_transcript_khong_co_dau_cach_".repeat(40));
  await submit();
  await b.wait("document.querySelectorAll('.ai-message').length === 7");
  await b.screenshot(`${output}/long-conversation-desktop.png`);
  await type(".ai-search input", "tai nghe pin lâu");
  await b.wait("document.querySelectorAll('.ai-message').length === 1");
  await check("Search filters the actual shared transcript", "document.querySelector('.ai-bubble').textContent === 'Tôi cần tai nghe pin lâu.'");
  await type(".ai-search input", "");
  await b.wait("document.querySelectorAll('.ai-message').length === 7");
  await type("#ai-message", "Giữ nháp với realtime");
  await upload();
  await b.wait("!!document.querySelector('audio')");
  await b.evaluate("window.__audioBeforeVoice = document.querySelector('audio').getAttribute('src')");
  await mode("realtime");
  await b.wait("!!document.querySelector('.voice-start') && !document.querySelector('.voice-start').disabled");
  await check("Realtime mode embeds one LiveKit surface without capturing the microphone on entry", "document.querySelectorAll('.realtime-voice').length === 1 && __test.mic === 0 && __test.voiceRequests.length === 0");
  await check("Voice owns a full dark viewport without chat input, chat history or sidebars", "document.querySelector('.ai-voice-workspace').getBoundingClientRect().height === innerHeight && !document.querySelector('.ai-composer') && !document.querySelector('.ai-message-list') && !document.querySelector('.ai-sidebar') && !document.querySelector('.ai-desktop-details') && !document.querySelector('input[type=file]') && getComputedStyle(document.body).backgroundColor === 'rgb(5, 8, 17)'");
  await check("The LiveKit panel is centered across the whole viewport", "(() => { const r=document.querySelector('.realtime-voice').getBoundingClientRect(); return Math.abs(r.left + r.width/2 - innerWidth/2) < 1; })()");
  await b.screenshot(`${output}/realtime-idle-desktop.png`);
  await click(".voice-start");
  await b.wait("document.querySelector('.voice-wave')?.dataset.lkState === 'listening'");
  await check("LiveKit uses the working voice client without rendering a text composer", "__test.mic === 1 && __test.sockets.length === 1 && !document.querySelector('#ai-message')");
  await b.evaluate("__test.sockets[0].emit({ type: 'transcript_update', turn_id: 'one', role: 'user', text: 'Mình cần tai nghe.' }); __test.sockets[0].emit({ type: 'transcript_update', turn_id: 'one', role: 'agent', text: 'Mình hỗ trợ bạn.' })");
  await b.wait("document.querySelectorAll('.voice-line').length === 2");
  await b.screenshot(`${output}/realtime-connected-desktop.png`);
  await click(".voice-mute");
  await check("Mute sends voice control to the existing socket", "__test.sockets[0].sent.some(value => typeof value === 'string' && JSON.parse(value).type === 'input_audio_end')");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
  await b.screenshot(`${output}/realtime-mobile.png`);
  await check("Realtime layout fits 320px", "document.documentElement.scrollWidth <= innerWidth");
  await check("Mobile voice controls fit within the viewport and both mode buttons remain reachable", "[...document.querySelectorAll('.voice-actions button, .ai-mode-bar button')].every(button => { const r=button.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth; }) && !document.querySelector('.ai-composer')");
  await mode("text");
  await b.wait("!document.querySelector('.realtime-voice') && !!document.querySelector('#ai-message') && !document.querySelector('.ai-send').disabled");
  await check("Changing mode ends the microphone and preserves the draft", "__test.stopped === 1 && document.querySelector('#ai-message').value === 'Giữ nháp với realtime'");
  await check("Returning to Chat restores the same audio File preview and history", "document.querySelector('audio').getAttribute('src') === __audioBeforeVoice && document.querySelector('.audio-preview').textContent.includes('ghi-am') && document.querySelectorAll('.ai-message').length === 7 && getComputedStyle(document.body).backgroundColor === 'rgb(255, 255, 255)'");
  await click(".audio-preview button");
  const longDraft = "Nhu cầu mua sắm cần được giữ khi chuyển chế độ. ".repeat(30);
  await type("#ai-message", longDraft);
  await mode("realtime");
  await b.wait("!!document.querySelector('.ai-voice-workspace')");
  await mode("text");
  await b.wait(`document.querySelector('#ai-message')?.value === ${JSON.stringify(longDraft)}`);
  await check("A long draft recovers its expanded composer after leaving Voice", "document.querySelector('#ai-message').getBoundingClientRect().height === 120 && __test.mic === 1");
  await type("#ai-message", "Giữ nháp với realtime");
  await b.evaluate("__test.voiceEnabled = false");
  await mode("realtime");
  await b.wait("document.querySelector('.voice-status')?.textContent === 'Voice chưa sẵn sàng'");
  await check("Unavailable Voice remains dark and allows a return to Chat", "document.querySelector('.voice-start').disabled && !document.querySelector('.ai-mode-bar button:first-child').disabled && !document.querySelector('.ai-composer') && __test.mic === 1");
  await b.screenshot(`${output}/realtime-unavailable-mobile.png`);
  await mode("text");
  await b.wait("!!document.querySelector('#ai-message')");
  await b.evaluate("__test.voiceEnabled = true");
  await b.evaluate("document.querySelector('.ai-message-scroll').scrollTop = 0");
  await b.screenshot(`${output}/chat-mobile.png`);
  await check("Long conversations and identifiers wrap at 320px", "document.documentElement.scrollWidth <= innerWidth && document.querySelector('#ai-message').getBoundingClientRect().bottom <= innerHeight");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 460, deviceScaleFactor: 1, mobile: false });
  await type("#ai-message", "Dòng dài trong ô nhập ".repeat(25));
  await check("Composer remains usable when the viewport shrinks for a keyboard", "document.querySelector('.ai-send').getBoundingClientRect().bottom <= innerHeight && document.querySelector('.ai-mode-bar').getBoundingClientRect().bottom < document.querySelector('.ai-composer').getBoundingClientRect().top");
  await type("#ai-message", "Giữ nháp với realtime");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
  await click(".ai-menu-trigger");
  await b.wait("!!document.querySelector('dialog[open] .ai-sidebar')");
  await check("Mobile history uses a modal with focus inside", "document.querySelector('dialog[open]').contains(document.activeElement)");
  await escape();
  await b.wait("!document.querySelector('dialog[open]')");
  await check("Escape restores keyboard focus", "document.activeElement === document.querySelector('.ai-menu-trigger')");
  await click(".ai-detail-button");
  await b.wait("!!document.querySelector('dialog[open] .ai-details')");
  await check("Mobile context drawer fits the viewport", "document.querySelector('dialog[open]').getBoundingClientRect().width <= innerWidth");
  await escape();
  await b.wait("!document.querySelector('dialog[open]')");
  await b.evaluate("__test.ready = false");
  await b.wait("document.querySelector('#ai-send-status').textContent.includes('Backend chưa sẵn sàng')");
  await check("Backend unavailability preserves drafts and explains disabled send", "document.querySelector('.ai-send').disabled && document.querySelector('#ai-message').value === 'Giữ nháp với realtime'");
  await b.evaluate("__test.ready = true");
  await b.wait("!document.querySelector('.ai-send').disabled");
  await check("Backend recovery requires manual retry", "__test.calls.length === 5");
  await b.send("Page.reload");
  await b.wait("document.querySelector('#ai-message')?.value === 'Giữ nháp với realtime'");
  await check("Refresh restores history and does not replay a send", "__test.calls.length === 0 && document.querySelectorAll('.ai-message').length === 7");
  await b.send("Page.navigate", { url: base + "/ai-chat?mode=offline" });
  await b.wait("document.querySelector('#ai-message')?.value === 'Giữ nháp với realtime'");
  await check("Legacy offline links resolve to the unified Chat without sending", "__test.calls.length === 0 && document.querySelectorAll('.ai-mode-bar button').length === 2 && document.querySelector('.ai-mode-bar button:first-child').getAttribute('aria-pressed') === 'true' && !document.querySelector('.realtime-voice')");
  await openDashboard();
  await b.evaluate("window.scrollTo({ top: 0, behavior: 'instant' })");
  await b.wait("!!document.querySelector('#inline-chat input[type=file]')");
  await check("Dashboard mode labels fit 320px", "document.documentElement.scrollWidth <= innerWidth && [...document.querySelectorAll('.mode-toggle button')].every(button => button.scrollWidth <= button.clientWidth)");
  await b.screenshot(`${output}/dashboard-entry-mobile.png`);
  await b.evaluate("window.scrollTo({ top: 0, behavior: 'instant' })");
  await b.wait("!!document.querySelector('#inline-chat input[type=file]')");
  await upload();
  await b.wait("location.pathname === '/ai-chat' && !!document.querySelector('audio')");
  await check("Dashboard upload hands off the File to Chat without creating another mode or sending", "document.querySelector('.audio-preview').textContent.includes('ghi-am') && __test.calls.length === 0 && location.search === '?mode=text' && document.querySelector('.ai-mode-bar button:first-child').getAttribute('aria-pressed') === 'true'");
  await b.screenshot(`${output}/chat-audio-mobile.png`);
  await click(".audio-preview button");
  await b.wait("!document.querySelector('audio')");
  await check("Removing audio restores the original text draft", "document.querySelector('#ai-message').value === 'Giữ nháp với realtime'");
  await openDashboard();
  await click(".mode-toggle button:last-child");
  await b.wait("location.pathname === '/ai-chat' && !!document.querySelector('.voice-start')");
  await check("Dashboard realtime mode opens the full workspace and keeps one voice UI", "document.querySelectorAll('.realtime-voice').length === 1 && !document.querySelector('.voice-dialog') && __test.mic === 0");
  await b.screenshot(`${output}/realtime-idle-mobile.png`);
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.screenshot(`${output}/realtime-desktop.png`);
  await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await b.wait("!!document.querySelector('[data-wave-fallback]')");
  await check("Reduced motion uses the LiveKit static fallback", "!document.querySelector('.voice-wave canvas')");
  await check("Voice has no offline audio picker; upload stays in Chat", "!document.querySelector('input[type=file]') && !document.querySelector('#ai-message')");
  await mode("text");
  await b.wait("!!document.querySelector('#ai-message')");
  await upload();
  await b.wait("!document.querySelector('.realtime-voice') && !!document.querySelector('audio')");
  await check("Chat still accepts offline audio after leaving Voice without starting a call", "__test.mic === 0 && document.querySelector('.ai-mode-bar button:first-child').getAttribute('aria-pressed') === 'true' && document.querySelectorAll('.ai-mode-bar button').length === 2");
  await click(".audio-preview button");
  await upload(0);
  await b.wait("document.querySelector('[role=alert]')?.textContent.includes('25 MB')");
  await check("Invalid audio is rejected without upload or losing the draft", "!document.querySelector('audio') && document.querySelector('#ai-message').value === 'Giữ nháp với realtime' && __test.calls.length === 0");
  await click(".ai-new-chat");
  await b.wait("!!document.querySelector('dialog[open] .ai-reset-actions')");
  await check("Creating a new conversation requires an explicit reset action", "document.querySelectorAll('.ai-message').length === 7");
  await click(".ai-reset-actions button:last-child");
  await b.wait("!document.querySelector('dialog[open]') && document.querySelectorAll('.ai-message').length === 1");
  await check("Confirmed new conversation resets transcript and draft but keeps customer identity", "document.querySelector('#ai-message').value === '' && document.querySelector('.ai-sidebar-footer strong').textContent === '0901234567'");
  await check("An empty conversation keeps only its sidebar navigation label and no redundant instruction", "document.querySelector('.ai-conversation-list strong').textContent === 'Cuộc trò chuyện mới' && document.querySelector('#ai-send-status').textContent === '' && !document.body.innerText.includes('Nhập tin nhắn hoặc chọn ghi âm để gửi.')");
  await b.screenshot(`${output}/chat-clean-desktop.png`);
  await b.evaluate("__test.denyMic = true");
  await mode("realtime");
  await b.wait("!!document.querySelector('.voice-start') && !document.querySelector('.voice-start').disabled");
  await click(".voice-start");
  await b.wait("document.querySelector('.realtime-voice [role=alert]')?.textContent.includes('Microphone bị từ chối')");
  await check("Microphone errors stay readable in the dark Voice surface and permit retry", "!document.querySelector('.voice-start').disabled && getComputedStyle(document.querySelector('.realtime-voice [role=alert]')).color === 'rgb(255, 198, 205)' && __test.voiceRequests.length === 0");
  await b.screenshot(`${output}/realtime-error-desktop.png`);
  await b.evaluate("__test.denyMic = false");
  await click(".voice-start");
  await b.wait("document.querySelector('.voice-wave')?.dataset.lkState === 'listening'");
  await openDashboard();
  await b.wait("__test.stopped === 1");
  await check("Leaving Voice for the dashboard closes the microphone and socket", "__test.sockets[0].readyState === 3 && __test.voiceRequests.some(request => request.method === 'DELETE') && !document.querySelector('.ai-voice-workspace')");
  console.log("AI chat browser regression complete");
} finally { await b.close(); }
