// Public preview: real UI fixtures, no mocked login and no backend required.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { connect } from "./browser-support.mjs";

const base = process.env.BASE_URL || "http://127.0.0.1:3100";
const output = process.env.BROWSER_ARTIFACT_DIR || "artifacts/salesman-demo";
await mkdir(output, { recursive: true });
const b = await connect();
const check = async (name, expression) => { assert.ok(await b.evaluate(expression), name); console.log("PASS", name); };
const click = selector => b.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const type = (selector, value) => b.evaluate(`(() => { const node=document.querySelector(${JSON.stringify(selector)}); Object.getOwnPropertyDescriptor(node.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(node,${JSON.stringify(value)}); node.dispatchEvent(new Event(node.tagName==='SELECT'?'change':'input',{bubbles:true})); })()`);
const search = async value => { await type("#sales-search", value); await click(".sales-search button"); };
const key = async (name, code, number) => {
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code, windowsVirtualKeyCode: number });
  await b.send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code, windowsVirtualKeyCode: number });
};

try {
  await b.send("Page.enable");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__demoRequests=[];
    window.__demoOriginalStorage={local:JSON.stringify({...localStorage}),session:JSON.stringify({...sessionStorage})};
    const originalFetch=window.fetch.bind(window);
    window.fetch=(input,options)=>{
      const url=new URL(input instanceof Request?input.url:String(input),location.origin);
      if(url.pathname.startsWith('/api/')){
        __demoRequests.push(url.pathname);
        return Promise.resolve(Response.json({detail:'Backend unavailable in preview test'},{status:503}));
      }
      return originalFetch(input,options);
    };
  ` });
  await b.send("Page.navigate", { url: base + "/salesman" });
  await b.wait("document.querySelectorAll('.sales-conversation').length===4 && document.querySelectorAll('.sales-message').length===6");
  await check("Demo opens without authentication or backend", "document.querySelector('.sales-account').textContent.includes('Salesman demo') && !document.querySelector('[role=alert]') && __demoRequests.length===0");
  await check("Sample data is clearly labeled and controls are read-only", "document.querySelector('.sales-demo-note').textContent.includes('Dữ liệu mẫu') && !document.querySelector('textarea,audio,.voice-start,.ai-new-chat,.cart-link')");
  await check("Header starts at the top and history spans Chat and Voice", "document.querySelector('.sales-header').getBoundingClientRect().top===0 && [...document.querySelectorAll('.sales-item-heading small')].some(n=>n.textContent==='Voice') && document.querySelector('.sales-list-heading').textContent.includes('8 hội thoại')");
  await b.screenshot(`${output}/history-desktop.png`);
  await click(".sales-tab-panel .sales-load-more");
  await b.wait("document.querySelectorAll('.sales-message').length===12");
  await check("Long transcript pagination preserves all messages", "!document.querySelector('.sales-tab-panel .sales-load-more') && new Set([...document.querySelectorAll('.sales-message p')].map(n=>n.textContent)).size===12");
  await click("#sales-tab-brief");
  await b.wait("!!document.querySelector('.sales-brief')");
  await check("Call brief shows summary, needs, objections and next steps", "document.querySelectorAll('.sales-brief section').length===4 && document.querySelector('.sales-brief').textContent.includes('sau 18:00') && document.querySelector('.sales-brief').textContent.includes('chi phí màng lọc')");
  await b.screenshot(`${output}/brief-desktop.png`);
  await click("#sales-tab-memory");
  await b.wait("!!document.querySelector('.sales-memory pre')");
  await check("Memory shows six categories and the selected customer's facts", "document.querySelectorAll('.sales-memory details').length===6 && document.querySelector('.sales-memory pre').textContent.includes('5000000')");
  await b.screenshot(`${output}/memory-desktop.png`);
  for (const width of [1440, 840, 375, 320]) {
    await b.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await check(`Layout wraps without horizontal scrolling at ${width}px`, "document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('.sales-tabs button,.sales-account a')].every(n=>n.getBoundingClientRect().right<=innerWidth)");
    if (width === 320) {
      await b.evaluate("document.querySelector('.sales-review').scrollIntoView({block:'start',behavior:'instant'})");
      await b.screenshot(`${output}/memory-mobile.png`);
    }
  }
  await b.evaluate("document.querySelector('#sales-tab-memory').focus()");
  await key("Home", "Home", 36);
  await check("Tabs support keyboard selection and focus", "document.activeElement.id==='sales-tab-messages' && document.activeElement.getAttribute('aria-selected')==='true'");
  await key("ArrowRight", "ArrowRight", 39);
  await check("Arrow keys select the next review tab", "document.activeElement.id==='sales-tab-brief' && !!document.querySelector('.sales-brief')");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false });
  await click(".sales-sidebar > .sales-load-more");
  await b.wait("document.querySelectorAll('.sales-conversation').length===8");
  await check("History pagination includes earlier sessions", "!document.querySelector('.sales-sidebar > .sales-load-more')");
  await search("le thu ha");
  await b.wait("document.querySelectorAll('.sales-conversation').length===2");
  await check("Accent-insensitive search finds multiple sessions of a customer", "[...document.querySelectorAll('.sales-item-heading strong')].every(n=>n.textContent==='Lê Thu Hà')");
  await search("no-match-example");
  await b.wait("!!document.querySelector('.sales-empty-list')");
  await check("Empty search clears the previous customer's details", "!document.querySelector('.sales-review-heading') && !document.querySelector('.sales-memory,.sales-brief,.sales-message')");
  await search("");
  await type("#sales-source", "voice");
  await b.wait("document.querySelectorAll('.sales-conversation').length===3 && document.querySelector('.sales-review-heading small')?.textContent.includes('demo-voice-002')");
  await click("#sales-tab-memory");
  await b.wait("!!document.querySelector('.sales-memory pre')");
  await check("Voice has its own saved example memory", "document.querySelector('.sales-memory pre').textContent.includes('8000000') && !document.querySelector('.sales-memory pre').textContent.includes('5000000')");
  await click(".sales-conversation:nth-child(2)");
  await b.wait("document.querySelectorAll('.sales-message').length===3");
  await check("Interrupted Voice transcript is marked", "document.querySelector('.sales-messages').textContent.includes('Chưa hoàn tất / bị ngắt')");
  await click("#sales-tab-brief");
  await check("Missing call brief has an explicit empty state", "document.querySelector('.sales-empty').textContent.includes('chưa lưu call brief')");
  await click("#sales-tab-memory");
  await check("Legacy Voice without memory has an explicit empty state", "document.querySelector('.sales-empty').textContent.includes('chưa lưu snapshot memory')");
  await type("#sales-source", "all");
  await search("demo-chat-008");
  await b.wait("!!document.querySelector('.sales-tab-panel .sales-empty') && document.querySelector('.sales-review-heading small')?.textContent.includes('demo-chat-008')");
  await click("#sales-tab-messages");
  await check("New empty conversation has no fabricated messages", "document.querySelector('.sales-empty').textContent.includes('Chưa có tin nhắn')");
  await search("minhanh@example.invalid");
  await b.wait("document.querySelectorAll('.sales-message').length===6");
  await click(".sales-review-heading button");
  await b.wait("document.querySelectorAll('.sales-message').length===6");
  await check("Refresh reads unchanged local fixtures without API requests", "__demoRequests.length===0 && document.querySelector('.sales-review-heading h2').textContent==='Nguyễn Minh Anh'");
  await b.evaluate("window.dispatchEvent(new Event('focus'))");
  await check("Demo preserves existing browser storage and avoids auth refresh", "__demoRequests.length===0 && JSON.stringify({...localStorage})===__demoOriginalStorage.local && JSON.stringify({...sessionStorage})===__demoOriginalStorage.session");
  await b.send("Page.reload", { ignoreCache: true });
  await b.wait("document.querySelectorAll('.sales-conversation').length===4 && document.querySelectorAll('.sales-message').length===6");
  await check("Direct reload remains accessible without an account", "__demoRequests.length===0 && location.pathname==='/salesman'");
  console.log("Salesman demo browser verification complete");
} catch (error) {
  console.error(await b.evaluate("({url:location.href,text:document.body.innerText.slice(0,1500),requests:window.__demoRequests})"));
  await b.screenshot(`${output}/failure.png`);
  throw error;
} finally { await b.close(); }
