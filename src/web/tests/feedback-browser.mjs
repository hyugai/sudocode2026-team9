import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { connect } from './browser-support.mjs';
const b=await connect(),base=process.env.BASE_URL||'http://127.0.0.1:3000',output=process.env.BROWSER_ARTIFACT_DIR||'/tmp/synee-feedback';
await mkdir(output,{recursive:true});
const checks=[];const check=(label,value)=>{assert.ok(value,label);checks.push(label);console.log('PASS',label);};
const click=s=>b.evaluate(`document.querySelector(${JSON.stringify(s)}).click()`);
const type=(s,value)=>b.evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(s)});Object.getOwnPropertyDescriptor(n.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(n,${JSON.stringify(value)});n.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const route=async path=>{await b.send('Page.navigate',{url:base+path});await b.wait("document.querySelector('.site-header')&&Object.keys(document.querySelector('.cart-link')||{}).some(k=>k.startsWith('__reactProps'))");await b.evaluate('document.fonts.ready');};
const snapshot=async name=>{await b.evaluate("window.scrollTo({top:0,behavior:'instant'});document.activeElement?.blur();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");const m=await b.send('Page.getLayoutMetrics'),s=m.cssContentSize||m.contentSize;const r=await b.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:s.width,height:s.height,scale:1}});await writeFile(`${output}/${name}.png`,Buffer.from(r.data,'base64'));};
try{
 await b.send('Page.enable');await b.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});await b.send('Emulation.setScrollbarsHidden',{hidden:true});
 if(process.argv.includes('--capture-before')){
  await route('/products/SKU-AP-X');await snapshot('before-pdp');await click('.commerce-actions button');await snapshot('before-account');
 }else{
  const runId=String(Date.now());
  await b.send('Page.addScriptToEvaluateOnNewDocument',{source:`
    if(sessionStorage.getItem('feedback.e2e.run')!==${JSON.stringify(runId)}){sessionStorage.clear();localStorage.removeItem('synee.demo.cart.v1');sessionStorage.setItem('feedback.e2e.run',${JSON.stringify(runId)});}
    window.__calls=[];window.__deleteStatus=200;const original=fetch.bind(window);
    window.fetch=async(input,options={})=>{const url=String(input);if(url.endsWith('/health'))return Response.json({status:'ok'});
    if(/\\/api\\/sessions\\//.test(url)){window.__calls.push({url,method:options.method});return Response.json({status:'cleared',conversation_id:decodeURIComponent(url.split('/').at(-1))},{status:window.__deleteStatus});}
    if(url.endsWith('/api/chat')){window.__calls.push({url,method:options.method,body:JSON.parse(options.body)});return Response.json({response:'Synee sẽ cùng bạn chọn sản phẩm.',normalized_message:JSON.parse(options.body).message});}return original(input,options);};
  `});
  await route('/');await b.wait("document.querySelector('#inline-message')&&!document.body.innerText.includes('Đang chờ kết nối backend')");
  await click('.account-trigger');await b.wait("document.querySelector('dialog.account-drawer[open] .save-profile')");
  check('Account opens as a right sidebar with profile, orders and history',await b.evaluate("(()=>{const d=document.querySelector('.account-drawer'),r=d.getBoundingClientRect();return r.right===1440&&r.width===440&&d.querySelectorAll('.account-navigation > a').length===3;})()"));
  check('Unsupported authentication is explicit and cannot submit credentials',await b.evaluate("document.querySelectorAll('.auth-unavailable button:disabled').length===3&&!document.querySelector('input[type=password]')&&document.querySelector('.auth-unavailable').textContent.includes('không phải thông tin đăng nhập')"));
  await type('#customer-phone','0901234567');await click('.save-profile');await click('.dialog-header button');
  await type('#inline-message','Tôi muốn xem máy lọc không khí');await b.evaluate("document.querySelector('.composer').requestSubmit()");await b.wait("document.querySelectorAll('.message').length===3");
  const id=await b.evaluate("window.__calls[0].body.conversation_id");
  await type('#inline-message','Giữ bản nháp này');await click('.mode-toggle button:last-child');
  await b.wait("document.querySelector('dialog[open] .realtime-voice')");
  await click('dialog[open] .dialog-header button');
  check('Header omits the removed category menu',await b.evaluate("!document.querySelector('.menu-button')&&!document.querySelector('.menu-links')"));
  await b.send('Page.reload');await b.wait("document.querySelector('#inline-message')?.value==='Giữ bản nháp này'");
  check('Reload restores messages, draft and Chat mode without an automatic send',await b.evaluate("document.querySelectorAll('.message').length===3&&document.querySelector('.mode-toggle button:first-child').getAttribute('aria-pressed')==='true'&&window.__calls.length===0"));
  await click('.account-trigger');check('Reload restores the exact ID and unverified phone hint',await b.evaluate(`document.querySelector('.session-id').textContent.includes(${JSON.stringify(id)})&&document.querySelector('#customer-phone').value==='0901234567'`));
  await snapshot('after-account');await click('.dialog-header button');
  await click('.product-card');await b.wait("document.querySelector('.pdp-ask')");await click('.pdp-ask');await b.wait("document.querySelector('.pdp-chat #floating-message')");
  check('PDP chat occupies a separate desktop column without obscuring product content',await b.evaluate("(()=>{const p=document.querySelector('.product-detail').getBoundingClientRect(),c=document.querySelector('.pdp-chat').getBoundingClientRect();return c.left>=p.right&&c.width>=360&&!document.querySelector('.floating-panel');})()"));
  check('PDP chat preserves exact context and draft without sending',await b.evaluate("document.querySelector('.consultation-context').textContent.includes('SKU-AP-X')&&document.querySelector('#floating-message').value==='Giữ bản nháp này'&&window.__calls.length===0"));
  await snapshot('after-pdp-chat');
  await b.send('Emulation.setDeviceMetricsOverride',{width:320,height:760,deviceScaleFactor:1,mobile:false});
  check('320px PDP chat stacks without page overflow',await b.evaluate("document.documentElement.scrollWidth<=320&&document.querySelector('.pdp-chat').getBoundingClientRect().width<=320"));
  await b.evaluate("document.querySelector('.pdp-chat').scrollIntoView({behavior:'instant'})");await snapshot('after-pdp-chat-mobile');
  await click('.close-chat');await b.wait("document.activeElement===document.querySelector('.pdp-ask')");check('Closing PDP chat restores keyboard focus to Ask Synee',await b.evaluate("document.activeElement===document.querySelector('.pdp-ask')"));
  await b.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await click('.pdp-purchase-actions .purchase-action');await b.wait("document.querySelector('.purchase-page')?.dataset.view==='checkout'");
  check('Checkout groups shipping and payment and omits redundant continue-shopping',await b.evaluate("document.querySelectorAll('fieldset.commerce-options').length===2&&[...document.querySelectorAll('.commerce-options label')].every(n=>getComputedStyle(n).borderTopWidth==='1px')&&!document.querySelector('.continue-shopping')"));
  await type('#delivery-name','Người nhận Demo');await type('#delivery-phone','0901234567');await type('#delivery-address','12 Đường Mẫu, Hà Nội');
  await snapshot('after-checkout');await b.evaluate("document.querySelector('.checkout-form').requestSubmit()");await b.wait("document.querySelector('.review-back')");
  check('Review exposes a back action before confirmation and no confusing retry copy',await b.evaluate("document.querySelector('.review-back').textContent.includes('Quay lại chỉnh sửa')&&!document.querySelector('.continue-shopping')&&!document.body.textContent.includes('Không tự gửi lại khi thất bại')"));
  await snapshot('after-review');await click('.confirmation input');await click('.order-summary .purchase-action');await b.wait("document.querySelector('.purchase-page')?.dataset.view==='success'");
  const orderId=await b.evaluate("JSON.parse(sessionStorage.getItem('synee.demo.purchase.v1')).orders[0].id");
  check('Success groups receipt and unpaid demo status with a working details link',await b.evaluate("document.querySelector('.success-banner').textContent.includes('Chưa thanh toán')&&document.querySelector('.success-banner').textContent.includes('DEMO-')&&!!document.querySelector('.continue-shopping')"));await snapshot('after-success');
  const isolated=await connect();try{await isolated.send('Page.enable');await isolated.send('Page.navigate',{url:base+`/orders/${orderId}`});await isolated.wait("document.querySelector('.purchase-page')?.textContent.includes('Không tìm thấy đơn demo')");check('Another guest tab cannot read the current tab demo receipt',await isolated.evaluate("!document.querySelector('.success-banner')&&!document.body.textContent.includes('Người nhận Demo')"));}finally{await isolated.close();}
  await click('.account-trigger');await click('.account-navigation a[href="/account/conversations"]');await b.wait("document.querySelector('.account-transcript')");
  check('History page restores the current guest transcript without claiming account ownership',await b.evaluate("document.querySelector('.account-transcript').textContent.includes('Tôi muốn xem máy lọc')&&document.querySelector('.account-history').textContent.includes('không phải lịch sử tài khoản')"));
  await click('.confirmation input');await b.evaluate('window.__deleteStatus=401');await click('.end-session');await b.wait("document.querySelector('.account-history .error')");
  check('Unauthorized session deletion retains history and allows manual recovery',await b.evaluate("document.querySelectorAll('.account-transcript article').length===3&&document.querySelector('.error').textContent.includes('chưa cấp quyền')"));
  await b.evaluate('window.__deleteStatus=200');await click('.end-session');await b.wait("document.querySelectorAll('.account-transcript article').length===1");
  check('End conversation calls the actual DELETE contract only after confirmation',await b.evaluate(`window.__calls.filter(c=>c.method==='DELETE').length===2&&window.__calls.at(-1).url.endsWith('/api/sessions/'+${JSON.stringify(id)})&&JSON.parse(sessionStorage.getItem('synee.guest.conversation.v1')).sessionId===''`));
  await click('.account-navigation a[href="/account"]');await b.wait("document.querySelector('.account-page #profile-phone')");
  await type('#profile-phone','0909999999');await click('.save-profile');
  check('Switching the guest identity requires consent before clearing previous purchase data',await b.evaluate("document.querySelector('.account-form .error').textContent.includes('Xác nhận')&&JSON.parse(sessionStorage.getItem('synee.demo.purchase.v1')).orders.length===1"));
  await click('.confirm-profile-reset');await click('.save-profile');
  check('Confirmed identity change clears prior receipt, checkout address and draft',await b.evaluate("(()=>{const p=JSON.parse(sessionStorage.getItem('synee.demo.purchase.v1')),c=JSON.parse(sessionStorage.getItem('synee.guest.conversation.v1'));return p===null&&c.customerPhone==='0909999999'&&c.input===''&&c.sessionId==='';})()"));
  await click('.account-trigger');
  check('Profile page and account drawer have unique accessible IDs',await b.evaluate("(()=>{const ids=[...document.querySelectorAll('[id]')].map(n=>n.id);return new Set(ids).size===ids.length&&!!document.querySelector('#profile-phone')&&!!document.querySelector('dialog #customer-phone');})()"));await click('.dialog-header button');
  await route('/?category='+encodeURIComponent('Điện gia dụng')+'#catalog-heading');await b.wait("document.querySelectorAll('.product-card').length===18");
  await click('.filter-status button');await b.wait("document.querySelectorAll('.product-card').length===40");
  check('Clearing filters restores the full BTC catalog without a View all button',await b.evaluate("document.querySelector('.category-nav button').getAttribute('aria-pressed')==='true'&&![...document.querySelectorAll('#catalog a')].some(link=>link.textContent.includes('Xem tất cả'))"));
  await b.send('Emulation.setDeviceMetricsOverride',{width:320,height:760,deviceScaleFactor:1,mobile:false});await b.evaluate("document.querySelector('.account-trigger').focus()");await click('.account-trigger');
  check('320px account drawer remains within the viewport',await b.evaluate("document.documentElement.scrollWidth<=320&&document.querySelector('.account-drawer').getBoundingClientRect().right<=320"));await snapshot('after-account-mobile');
  await b.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await b.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await b.wait("!document.querySelector('dialog[open]')");
  await b.wait("document.activeElement===document.querySelector('.account-trigger')");
  check('Escape closes the account sidebar and returns focus to its trigger',await b.evaluate("document.activeElement===document.querySelector('.account-trigger')"));
  await writeFile(`${output}/results.json`,JSON.stringify({checks,orderId},null,2));console.log(`${checks.length} feedback browser checks passed.`);
 }
}finally{await b.close();}
