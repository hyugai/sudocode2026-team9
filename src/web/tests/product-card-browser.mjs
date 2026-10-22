import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { connect } from "./browser-support.mjs";

const browser = await connect();
const output = process.env.BROWSER_ARTIFACT_DIR || "/tmp/synee-product-cards";
const base = process.env.BASE_URL || "http://localhost:3000";
await mkdir(output, { recursive: true });
const checks = [];
const check = (name, value) => { assert.ok(value, name); checks.push(name); console.log("PASS", name); };
const type = (selector, value) => browser.evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(n.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(n,${JSON.stringify(value)});n.dispatchEvent(new Event('input',{bubbles:true}));})()`);
try {
  await browser.send("Page.enable");
  await browser.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__calls=[];
    const originalFetch=window.fetch.bind(window);
    window.fetch=async(input,options={})=>{
      const url=String(input);
      if(url.endsWith('/health'))return Response.json({status:'ok'});
      if(!/\\/api\\/chat(?:\\/audio)?$/.test(url))return originalFetch(input,options);
      window.__calls.push({url,body:options.body});
      return Response.json({response:'Đã ghi nhận.',normalized_message:JSON.parse(options.body).message});
    };` });
  await browser.send("Emulation.setScrollbarsHidden", { hidden: true });
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await browser.send("Page.navigate", { url: base });
  await browser.wait("document.querySelector('#inline-message')&&!document.body.innerText.includes('Đang chờ kết nối backend')");
  await browser.evaluate("document.fonts.ready");
  await browser.evaluate("document.querySelector('#catalog').scrollIntoView({behavior:'instant'})");
  if (process.argv.includes("--capture-before")) {
    await browser.screenshot(`${output}/before-desktop.png`);
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
    await browser.screenshot(`${output}/before-mobile.png`);
  } else {
    check("No obsolete card action, wrapper or nested interactive control", await browser.evaluate("!document.querySelector('.ask-product')&&![...document.querySelectorAll('.product-card')].some(n=>n.querySelector('button,a,input'))&&!document.querySelector('.product-grid').textContent.includes('Hỏi AI về sản phẩm')"));
    const links = await browser.evaluate("[...document.querySelectorAll('.product-card')].map(n=>({sku:n.dataset.sku,name:n.querySelector('h3').textContent,href:n.getAttribute('href'),height:n.getBoundingClientRect().height,width:n.getBoundingClientRect().width}))");
    check("All 40 cards are native links to their own SKU PDP", links.length === 40 && links.every(p => p.href === `/products/${encodeURIComponent(p.sku)}`));
    check("Desktop cards match 224 × 338 with no CTA gap", links.every(p => p.width === 224 && p.height === 338));
    await browser.screenshot(`${output}/after-desktop.png`);
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
    check("Mobile cards align and stay inside the page", await browser.evaluate("document.documentElement.scrollWidth<=320&&new Set([...document.querySelectorAll('.product-card')].map(n=>n.getBoundingClientRect().height)).size===1"));
    await browser.screenshot(`${output}/after-mobile.png`);
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate("window.scrollTo({top:0,behavior:'instant'})");
    await browser.wait("document.querySelector('#inline-message')");
    await browser.evaluate("document.querySelector('.commerce-actions button:last-child').click()");
    await type("#customer-phone", "0901234567");
    await browser.evaluate("document.querySelector('.dialog-header button').click()");
    await type("#inline-message", "Giữ bản nháp khi mở sản phẩm");
    await browser.evaluate("document.querySelector('.composer').requestSubmit()");
    await browser.wait("document.querySelectorAll('.message').length===3");
    const sent = await browser.evaluate("JSON.parse(window.__calls[0].body)");
    await type("#inline-message", "Bản nháp được giữ");
    await browser.evaluate("document.querySelector('.catalog-tabs button').focus()");
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
    check("Whole card receives visible keyboard focus", await browser.evaluate("document.activeElement.classList.contains('product-card')&&getComputedStyle(document.activeElement).outlineStyle!=='none'"));
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", text: "\r", windowsVirtualKeyCode: 13 });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await browser.wait("location.pathname==='/products/SKU-AP-X'&&document.querySelector('.product-detail h1')");
    check("Enter opens the matching SKU PDP with original product information", await browser.evaluate("document.querySelector('.product-detail').dataset.sku==='SKU-AP-X'&&document.querySelector('h1').textContent==='Máy lọc không khí AirPure X'&&document.querySelector('.product-detail .price').textContent==='4.890.000₫'"));
    await browser.evaluate("document.querySelector('.chat-launcher').click()");
    await browser.wait("document.querySelector('#floating-message')");
    check("PDP navigation preserves chat history and draft without a new request", await browser.evaluate(`document.querySelectorAll('.message').length===3&&document.querySelector('#floating-message').value==='Bản nháp được giữ'&&window.__calls.length===1`));
    await browser.evaluate("document.querySelector('.commerce-actions button:last-child').click()");
    check("Phone and conversation ID survive navigation", await browser.evaluate(`document.querySelector('#customer-phone').value==='0901234567'&&document.querySelector('.session-id').textContent.includes(${JSON.stringify(sent.conversation_id)})`));
    await browser.evaluate("document.querySelector('.dialog-header button').click()");
    await browser.evaluate("document.querySelector('.pdp-ask').click()");
    await browser.wait("document.querySelector('.consultation-context').textContent.includes('SKU-AP-X')");
    check("PDP consultation preserves the existing draft", await browser.evaluate("document.querySelector('#floating-message').value==='Bản nháp được giữ'"));
    check("Hỏi Synee AI exists only on PDP and never auto-submits", await browser.evaluate("document.querySelector('.pdp-ask').textContent.includes('Hỏi Synee AI')&&window.__calls.length===1"));
    await browser.screenshot(`${output}/pdp-desktop.png`);
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate("document.querySelector('.close-chat').click()");
    check("PDP remains usable at 320px", await browser.evaluate("document.documentElement.scrollWidth<=320"));
    await browser.screenshot(`${output}/pdp-mobile.png`);
    for (const sku of ["SKU-WF-RO9", "SKU-SN-RUN2", "SKU-AP-FLT-X"]) {
      await browser.evaluate(`document.querySelector('.pdp-back').click()`);
      await browser.wait("document.querySelector('.product-grid')");
      await browser.evaluate(`document.querySelector('[data-sku="${sku}"]').click()`);
      await browser.wait(`document.querySelector('.product-detail')?.dataset.sku==='${sku}'`);
      check(`Pointer click opens ${sku}`, await browser.evaluate(`location.pathname==='/products/${sku}'`));
    }
    await browser.evaluate("document.querySelector('.pdp-back').click()");
    await browser.wait("document.querySelector('.product-grid')");
    await browser.evaluate("window.scrollTo({top:0,behavior:'instant'})");
    await browser.wait("document.querySelector('#inline-message')");
    await browser.evaluate("(()=>{const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(44)],'preserved.wav',{type:'audio/wav'}));const n=document.querySelector('.composer input[type=file]');n.files=dt.files;n.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await browser.wait("document.querySelector('audio')");
    const audioUrl = await browser.evaluate("document.querySelector('audio').src");
    await browser.evaluate("document.querySelector('.product-card').click()");
    await browser.wait("document.querySelector('.pdp-ask')");
    await browser.evaluate("document.querySelector('.chat-launcher').click()");
    await browser.wait("document.querySelector('audio')");
    check("PDP navigation preserves the selected audio and preview URL", await browser.evaluate(`document.querySelector('audio').src===${JSON.stringify(audioUrl)}&&document.body.textContent.includes('preserved.wav')`));
    check("PDP AI action protects the selected audio", await browser.evaluate("document.querySelector('.pdp-ask').disabled"));
    await browser.evaluate("document.querySelector('.audio-preview button').click()");
    const routes = await browser.evaluate(`Promise.all(${JSON.stringify(links)}.map(async p=>{const r=await fetch(p.href);const text=await r.text();return {sku:p.sku,status:r.status,correct:text.includes('data-sku="'+p.sku+'"')&&text.includes(p.name.replaceAll('&','&amp;'))};}))`);
    check("Every catalog SKU has a successful detail route", routes.every(r => r.status === 200 && r.correct));
    check("Unknown SKU returns 404", await browser.evaluate("fetch('/products/SKU-DOES-NOT-EXIST').then(r=>r.status===404)"));
    await browser.evaluate("document.querySelector('.close-chat').click()");
    await type("#product-search", "SKU-WF-RO9");
    await browser.evaluate("document.querySelector('.product-search').requestSubmit()");
    await browser.wait("location.pathname==='/'&&document.querySelectorAll('.product-card').length===1");
    check("Shared header search returns to the correct catalog result", await browser.evaluate("document.querySelector('.product-card').dataset.sku==='SKU-WF-RO9'"));
    await writeFile(`${output}/results.json`, JSON.stringify({ checks, links, routes }, null, 2));
  }
} catch (error) {
  console.error(await browser.evaluate("({url:location.href,text:document.body.innerText.slice(0,1200)})"));
  throw error;
} finally { await browser.close(); }
