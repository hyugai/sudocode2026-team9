// Local browser integration: navigation and draft continuity use the real app;
// chat/voice calls are intercepted so this suite never contacts an AI service.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chatRecommendations } from "../utils/chat-recommendations.ts";
import { connect } from "./browser-support.mjs";

const b = await connect();
const base = process.env.BASE_URL || "http://127.0.0.1:3400";
const output = process.env.BROWSER_ARTIFACT_DIR || fileURLToPath(new URL("../../../outputs/debug/streaming-ui/dashboard-recommendations/", import.meta.url));
await mkdir(output, { recursive: true });
const check = async (name, expression) => { assert.ok(await b.evaluate(expression), name); console.log("PASS", name); };
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const click = selector => b.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const dashboard = async () => {
  await click(".ai-exit-link");
  await b.wait("location.pathname === '/' && !!document.querySelector('.hero')");
  // Wait for Next's restored scroll before normalizing the launcher position.
  await b.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  await b.wait("(window.scrollTo({ top: 0, behavior: 'instant' }), !!document.querySelector('#inline-message') && !document.querySelector('.recommendation-group button').disabled)");
};
const position = () => b.evaluate("document.querySelector('.recommendation-viewport').scrollLeft");

try {
  await b.send("Page.enable");
  await b.send("Page.bringToFront");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    if (!sessionStorage.getItem('recommendation-test-seeded')) {
      sessionStorage.clear();
      sessionStorage.setItem('recommendation-test-seeded', '1');
      sessionStorage.setItem('synee.guest.conversation.v1', JSON.stringify({ version: 1,
        messages: [{ role: 'agent', text: 'Xin chào từ Synee.' }, { role: 'user', text: 'Lịch sử đã có về AirPure X.' }, { role: 'agent', text: 'Nội dung cũ được giữ trong trang chat.' }],
        input: '', sessionId: '12345678-1234-4234-8234-123456789abc', customerPhone: '0901234567', voicePreview: false, consultation: null }));
    }
    window.__recommendations = { calls: [], ready: true };
    const originalFetch = fetch.bind(window);
    window.fetch = async (input, options = {}) => {
      const url = String(input);
      if (url.endsWith('/health')) return Response.json({}, { status: __recommendations.ready ? 200 : 503 });
      if (/\\/api\\/chat(?:\\/audio)?$/.test(url)) {
        __recommendations.calls.push({ url, body: options.body });
        return Response.json({ response: 'Phản hồi kiểm thử.' });
      }
      if (url.endsWith('/api/voice/capabilities')) return Response.json({ enabled: false, requires_access_code: false });
      return originalFetch(input, options);
    };
  ` });
  await b.send("Page.navigate", { url: base });
  await b.wait("!!document.querySelector('.recommendation-group button') && !document.querySelector('.recommendation-group button').disabled");
  await b.evaluate("document.fonts.ready");
  await check("Dashboard hides the transcript without clearing stored conversation", "!document.querySelector('#inline-chat [role=log]') && !document.querySelector('#inline-chat .conversation-history') && JSON.parse(sessionStorage.getItem('synee.guest.conversation.v1')).messages.length === 3");
  await check("Exactly 30 distinct recommendations have one accessible copy", "document.querySelectorAll('.recommendation-group:not([aria-hidden]) button').length === 30 && new Set([...document.querySelectorAll('.recommendation-group:not([aria-hidden]) button')].map(b=>b.textContent)).size === 30 && [...document.querySelectorAll('.recommendation-group[aria-hidden] button')].every(b=>b.tabIndex === -1)");
  await check("Dashboard omits recommendation heading, pause button and session footer", "!document.querySelector('.recommendation-heading') && !document.querySelector('.recommendation-pause') && !document.querySelector('#inline-chat .resume-prompt') && !document.querySelector('#inline-chat').innerText.includes('30 câu hỏi')");
  const start = await position();
  await b.wait(`document.querySelector('.recommendation-viewport').scrollLeft > ${start + 10}`);
  console.log("PASS Suggestions advance automatically");

  // Exercise the actual loop boundary without waiting for the full 30-item lap.
  await b.evaluate("document.querySelector('.recommendation-viewport').focus()");
  const beforeFocus = await position();
  await delay(250);
  assert.equal(await position(), beforeFocus, "Keyboard focus pauses the strip");
  await b.evaluate("const v = document.querySelector('.recommendation-viewport'); v.scrollLeft = document.querySelector('.recommendation-group').getBoundingClientRect().width - 2; document.querySelector('#inline-message').focus({preventScroll:true})");
  await b.wait("document.querySelector('.recommendation-viewport').scrollLeft < 100");
  console.log("PASS Seamless loop returns to the beginning and keyboard focus pauses motion");
  await b.screenshot(`${output}/after-desktop.png`);

  for (const [index, item] of chatRecommendations.entries()) {
    await b.wait("document.querySelectorAll('.recommendation-group:not([aria-hidden]) button').length === 30");
    await b.evaluate(`document.querySelectorAll('.recommendation-group:not([aria-hidden]) button')[${index}].click()`);
    await b.wait(`location.pathname === '/ai-chat' && document.querySelector('#ai-message')?.value === ${JSON.stringify(item.text)}`);
    assert.equal(await b.evaluate("__recommendations.calls.length"), 0, "Selecting a recommendation never sends a request");
    assert.equal(await b.evaluate("document.querySelectorAll('.ai-message').length"), 3, "Original history stays intact");
    if (index < chatRecommendations.length - 1) await dashboard();
  }
  console.log("PASS All 30 selections open the workspace with the correct draft and retained history; none auto-send");
  await b.send("Page.reload");
  await b.wait(`document.querySelector('#ai-message')?.value === ${JSON.stringify(chatRecommendations.at(-1).text)}`);
  await check("Refresh preserves the selected draft and never replays a send", "__recommendations.calls.length === 0 && document.querySelectorAll('.ai-message').length === 3");
  await dashboard();

  await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await b.wait("getComputedStyle(document.querySelector('.recommendation-group[aria-hidden]')).display === 'none'");
  const reducedStart = await position();
  await delay(300);
  assert.equal(await position(), reducedStart, "Reduced motion stops scrolling");
  await check("Reduced motion keeps the 30 original buttons and hides the visual duplicate", "getComputedStyle(document.querySelector('.recommendation-group[aria-hidden]')).display === 'none' && document.querySelectorAll('.recommendation-group:not([aria-hidden]) button').length === 30");

  // Focus the last, initially offscreen recommendation and activate via keyboard.
  await b.evaluate("document.querySelector('.recommendation-group:not([aria-hidden]) button:last-child').focus()");
  await check("Keyboard can reveal an offscreen recommendation", "(() => { const v=document.querySelector('.recommendation-viewport').getBoundingClientRect(); const r=document.activeElement.getBoundingClientRect(); return r.left >= v.left && r.right <= v.right; })()");
  await b.send("Page.bringToFront");
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13 });
  await b.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await b.wait("location.pathname === '/ai-chat'");
  await check("Keyboard activation uses the same draft handoff", `document.querySelector('#ai-message').value === ${JSON.stringify(chatRecommendations.at(-1).text)} && __recommendations.calls.length === 0`);
  await dashboard();

  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 740, deviceScaleFactor: 1, mobile: true });
  await b.send("Emulation.setTouchEmulationEnabled", { enabled: true });
  await b.evaluate("window.scrollTo({top:0,behavior:'instant'})");
  await b.wait("document.querySelector('.site-header').getBoundingClientRect().height === 136");
  await check("At 320px the launcher fits, text wraps, controls remain usable and catalog starts below the first viewport", "document.documentElement.scrollWidth <= innerWidth && document.querySelector('#inline-chat').getBoundingClientRect().width <= 288 && document.querySelector('.recommendation-group button').getBoundingClientRect().height >= 44 && document.querySelector('#catalog').getBoundingClientRect().top >= innerHeight");
  await b.screenshot(`${output}/after-mobile.png`);
  await b.evaluate("document.querySelector('.browse-action').click()");
  await b.wait("document.querySelector('#catalog').getBoundingClientRect().top < innerHeight && !!document.querySelector('.chat-launcher')");
  await b.evaluate("document.querySelector('.chat-launcher').click()");
  await b.wait("!!document.querySelector('#floating-chat .conversation-history')");
  await check("Catalog floating chat still shows retained conversation history", "document.querySelectorAll('#floating-chat .message').length === 3");
  await b.evaluate("document.querySelector('.close-chat').click(); document.querySelector('.back-to-ai').click()");
  await b.wait("!!document.querySelector('#inline-chat')");
  await check("Returning from the catalog does not reveal dashboard history", "!document.querySelector('#inline-chat [role=log]') && document.documentElement.scrollWidth <= innerWidth");
  await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await b.wait("getComputedStyle(document.querySelector('.recommendation-group[aria-hidden]')).display !== 'none'");
  await b.evaluate("document.querySelector('#inline-message').focus({preventScroll:true}); window.scrollTo({top:0,behavior:'instant'})");
  const beforeTouch = await position();
  await b.wait(`document.querySelector('.recommendation-viewport').scrollLeft > ${beforeTouch + 5}`);
  const touchStart = await b.evaluate("(() => { const viewport = document.querySelector('.recommendation-viewport'); viewport.dispatchEvent(new PointerEvent('pointerdown',{pointerType:'touch',bubbles:true})); return viewport.scrollLeft; })()");
  await delay(250);
  assert.equal(await position(), touchStart, "Touch drag temporarily pauses motion");
  await b.evaluate("window.dispatchEvent(new PointerEvent('pointerup',{pointerType:'touch'}))");
  await b.wait(`document.querySelector('.recommendation-viewport').scrollLeft > ${touchStart + 5}`);
  console.log("PASS Suggestions automatically resume after touch browsing without a pause control");
} catch (error) {
  console.log("Browser failure", await b.evaluate("({path:location.href,scroll:scrollY,focus:document.activeElement.outerHTML.slice(0,400),inline:document.querySelector('.inline-chat-mount')?.outerHTML.slice(0,700),hero:document.querySelector('.hero')?.getBoundingClientRect().toJSON(),suggestions:document.querySelectorAll('.suggestion').length})"));
  await b.screenshot(`${output}/debug-failed-selection.png`);
  throw error;
} finally {
  await b.close();
}
