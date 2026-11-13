// Real UI with synthetic API responses. Run the separate backend integration tests too.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { salesmanDemo } from "../utils/salesman-demo.ts";
import { connect } from "./browser-support.mjs";

const base = process.env.BASE_URL || "http://127.0.0.1:3100";
const output = process.env.BROWSER_ARTIFACT_DIR || fileURLToPath(new URL("../../../outputs/debug/streaming-ui/salesman/", import.meta.url));
await mkdir(output, { recursive: true });
const first = await salesmanDemo.list("", "all");
const second = await salesmanDemo.list("", "all", first.items.length);
const items = [...first.items, ...second.items];
const details = {};
for (const item of items) {
  const value = await salesmanDemo.get(item.source, item.id);
  if (value.has_more) value.messages.push(...(await salesmanDemo.get(item.source, item.id, value.next_offset)).messages);
  details[`${item.source}:${item.id}`] = value;
}
const b = await connect();
const check = async (name, expression) => { assert.ok(await b.evaluate(expression), name); console.log("PASS", name); };
const click = selector => b.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const type = (selector, value) => b.evaluate(`(() => { const node=document.querySelector(${JSON.stringify(selector)}); Object.getOwnPropertyDescriptor(node.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(node,${JSON.stringify(value)}); node.dispatchEvent(new Event(node.tagName==='SELECT'?'change':'input',{bubbles:true})); })()`);
const search = async value => { await type("#sales-search", value); await click(".sales-search button"); };
try {
  await b.send("Page.enable");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__salesRequests=[];
    window.__salesMode='ok';
    window.__salesRole=sessionStorage.getItem('sales-test-role') || 'salesman';
    window.__salesAuthUnavailable=sessionStorage.getItem('sales-test-auth-error')==='1';
    const items=${JSON.stringify(items)}, details=${JSON.stringify(details)};
    const normalize=s=>s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/đ/g,'d');
    const native=fetch.bind(window);
    window.fetch=async(input,options={})=>{
      const url=new URL(input instanceof Request?input.url:String(input),location.origin);
      const path=url.pathname;
      if(!path.startsWith('/api/')) return native(input,options);
      __salesRequests.push({path,method:options.method||'GET'});
      const user={id:'sales-test',name:'Salesman kiểm thử',email:'sales@example.invalid',role:__salesRole};
      if(path==='/api/auth/me') return __salesAuthUnavailable?Response.json({detail:'Chưa kết nối được dịch vụ tài khoản'},{status:503}):__salesRole==='guest'?Response.json({detail:'Hết phiên'},{status:401}):Response.json({user});
      if(path==='/api/auth/logout') { __salesRole='guest'; sessionStorage.setItem('sales-test-role','guest'); return Response.json({status:'logged_out'}); }
      if(path==='/api/auth/login') { __salesRole='salesman'; __salesMode='ok'; sessionStorage.setItem('sales-test-role','salesman'); return Response.json({user:{...user,role:'salesman'}}); }
      if(path.startsWith('/api/salesman/')){
        if(__salesMode==='expired') { __salesRole='guest'; sessionStorage.setItem('sales-test-role','guest'); return Response.json({detail:'Phiên đã hết hạn'},{status:401}); }
        if(__salesMode==='error') return Response.json({detail:'Chưa kết nối được lịch sử'},{status:503});
        const offset=Number(url.searchParams.get('offset')||0);
        if(path==='/api/salesman/conversations'){
          const source=url.searchParams.get('source'), query=normalize(url.searchParams.get('q')||'');
          if(query==='slow') await new Promise(resolve=>setTimeout(resolve,500));
          options.signal?.throwIfAborted();
          const filtered=items.filter(i=>(source==='all'||i.source===source)&&normalize([i.user_name,i.user_email,i.customer_phone,i.id,i.customer_id].join(' ')).includes(query));
          return Response.json({items:filtered.slice(offset,offset+4),total:filtered.length,has_more:offset+4<filtered.length});
        }
        const parts=path.split('/'), row=details[parts[4]+':'+decodeURIComponent(parts[5])];
        if(!row) return Response.json({detail:'Không tìm thấy'},{status:404});
        return Response.json({...row,messages:row.messages.slice(offset,offset+6),next_offset:offset+Math.min(6,row.messages.length-offset),has_more:offset+6<row.messages.length});
      }
      if(path==='/api/health') return Response.json({status:'ready'});
      return Response.json({detail:'Not part of the Salesman flow'},{status:404});
    };
  ` });
  await b.send("Page.navigate", { url: base + "/salesman" });
  await b.wait("document.querySelectorAll('.sales-conversation').length===4 && document.querySelectorAll('.sales-message').length===6");
  await check("Authenticated Salesman loads the history API and account identity", "document.querySelector('.sales-account').textContent.includes('Salesman kiểm thử') && __salesRequests.some(r=>r.path==='/api/auth/me') && __salesRequests.some(r=>r.path==='/api/salesman/conversations')");
  await check("No chat/cart/microphone providers or demo fallback on the review page", "!document.querySelector('textarea,audio,.voice-start,.ai-new-chat,.cart-link') && !__salesRequests.some(r=>r.path==='/api/health'||r.path.includes('/api/catalog')) && !document.querySelector('.sales-demo-note').textContent.includes('Dữ liệu mẫu')");
  await b.screenshot(`${output}/history-desktop.png`);
  await click(".sales-tab-panel .sales-load-more");
  await b.wait("document.querySelectorAll('.sales-message').length===12");
  await check("Transcript pagination keeps every message once", "new Set([...document.querySelectorAll('.sales-message p')].map(n=>n.textContent)).size===12");
  await click("#sales-tab-brief");
  await check("Call brief renders four saved fields", "document.querySelectorAll('.sales-brief section').length===4");
  await click("#sales-tab-memory");
  await check("Memory is labeled as the saved end-of-turn version", "document.querySelectorAll('.sales-memory details').length===6 && document.querySelector('.sales-memory').textContent.includes('Bản lưu cuối lượt')");
  await b.evaluate("document.getElementById('sales-tab-messages').focus()");
  await b.send("Input.dispatchKeyEvent", { type:"keyDown", key:"ArrowRight", code:"ArrowRight", windowsVirtualKeyCode:39 });
  await check("Review tabs support keyboard navigation", "document.activeElement.id==='sales-tab-brief' && document.activeElement.getAttribute('aria-selected')==='true'");
  for (const width of [320,375,768,1440]) {
    await b.send("Emulation.setDeviceMetricsOverride", { width,height:960,deviceScaleFactor:1,mobile:false });
    await check(`Content wraps at ${width}px`, "document.documentElement.scrollWidth<=innerWidth");
    if(width===320) await b.screenshot(`${output}/history-mobile.png`);
  }
  await click(".sales-sidebar > .sales-load-more");
  await b.wait("document.querySelectorAll('.sales-conversation').length===8");
  await search("le thu ha");
  await b.wait("document.querySelectorAll('.sales-conversation').length===2");
  await check("Search handles Vietnamese diacritics", "[...document.querySelectorAll('.sales-item-heading strong')].every(n=>n.textContent==='Lê Thu Hà')");
  await search("slow");
  await search("demo-chat-001");
  await b.wait("document.querySelectorAll('.sales-conversation').length===1 && document.querySelectorAll('.sales-message').length===6");
  await b.evaluate("new Promise(resolve=>setTimeout(resolve,600))");
  await check("An old search cannot overwrite the selected customer's data", "document.querySelector('.sales-review-heading small').textContent.includes('demo-chat-001') && document.querySelectorAll('.sales-conversation').length===1");
  await search("");
  await type("#sales-source","voice");
  await b.wait("document.querySelectorAll('.sales-conversation').length===3");
  await search("demo-voice-004");
  await b.wait("!!document.querySelector('.sales-message span')");
  await check("Interrupted Voice transcript is explicit", "document.querySelector('.sales-messages').textContent.includes('Chưa hoàn tất / bị ngắt')");
  await click("#sales-tab-memory");
  await check("Legacy Voice without snapshot has an empty state", "document.querySelector('.sales-empty').textContent.includes('chưa lưu snapshot memory')");
  await b.evaluate("__salesMode='error'");
  await click(".sales-list-heading button");
  await b.wait("!!document.querySelector('.sales-error')");
  await check("Unavailable backend clears old details and never falls back to fixtures", "document.querySelectorAll('.sales-conversation').length===0 && !document.querySelector('.sales-message,.sales-memory')");
  await b.evaluate("__salesMode='ok'");
  await click(".sales-error button");
  await b.wait("document.querySelectorAll('.sales-conversation').length===1");
  await check("Retry reloads data manually", "document.querySelector('.sales-review-heading small').textContent.includes('demo-voice-004')");
  await b.evaluate("__salesMode='expired'");
  await click(".sales-list-heading button");
  await b.wait("location.pathname==='/login' && !!document.querySelector('#auth-email')");
  await check("Session expiry removes private history before login", "!document.querySelector('.sales-message,.sales-memory,.sales-conversation')");
  await type("#auth-email","sales@example.invalid");
  await type("#auth-password","Demo2026");
  await click(".auth-submit");
  await b.wait("location.pathname==='/salesman' && !!document.querySelector('.sales-account button')");
  await check("Salesman login redirects to the workspace", "document.querySelector('.sales-account').textContent.includes('Salesman kiểm thử')");
  await click(".sales-account button");
  await b.wait("location.pathname==='/login'");
  await check("Logout removes the workspace", "!document.querySelector('.sales-message,.sales-memory')");
  await b.evaluate("sessionStorage.setItem('sales-test-role','user')");
  await b.send("Page.navigate",{url:base+'/salesman'});
  await b.wait("location.pathname==='/'");
  await check("A regular user cannot mount the Salesman workspace", "!document.querySelector('.sales-workspace') && !__salesRequests.some(r=>r.path.startsWith('/api/salesman/'))");
  await b.evaluate("sessionStorage.setItem('sales-test-auth-error','1')");
  await b.send("Page.navigate",{url:base+'/login'});
  await b.wait("document.body.innerText.includes('Chưa xác nhận được phiên đăng nhập')");
  await check("Auth failure offers retry instead of an endless loading screen", "!!document.querySelector('[role=alert] button') && !document.body.innerText.includes('Đang kiểm tra phiên đăng nhập…')");
  await b.evaluate("__salesAuthUnavailable=false; sessionStorage.removeItem('sales-test-auth-error')");
  await click("[role=alert] button");
  await b.wait("!!document.querySelector('#auth-email')");
  console.log("Salesman live-contract browser verification complete");
} catch (error) {
  console.error(await b.evaluate("({url:location.href,text:document.body.innerText.slice(0,1800),requests:window.__salesRequests})"));
  throw error;
} finally { await b.close(); }
