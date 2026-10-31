// Unmocked, non-destructive browser checks for the current unavailable backend.
// Never sends chat/audio/order POSTs and never creates customer records.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { connect } from './browser-support.mjs';

const b = await connect();
const base = process.env.BASE_URL || 'http://localhost:3000';
const output = '/tmp/synee-m3/unmocked';
await mkdir(output, { recursive:true });
const requests = [], checks = [];
const check = (name, value) => { assert.ok(value, name); checks.push(name); console.log('PASS', name); };
const route = async path => {
  await b.send('Page.navigate', { url:base + path });
  await b.wait("document.querySelector('.account-trigger')&&Object.keys(document.querySelector('.account-trigger')).some(k=>k.startsWith('__reactProps'))");
  await b.evaluate('document.fonts.ready');
};
try {
  await b.send('Page.enable'); await b.send('Network.enable');
  b.on('Network.requestWillBeSent', ({ request }) => {
    if (request.url.startsWith('http://localhost:8000') || request.url.startsWith('http://127.0.0.1:8000')) requests.push({ method:request.method, url:request.url });
  });
  await b.send('Emulation.setDeviceMetricsOverride', { width:1440, height:1000, deviceScaleFactor:1, mobile:false });
  await route('/'); await b.wait("document.querySelector('.chat-status').textContent.includes('Đang chờ kết nối backend')");
  check('Unmocked UI reports unavailable backend instead of inventing a response', await b.evaluate("document.querySelector('.composer .press-button').disabled&&document.querySelectorAll('.message').length===1"));
  await b.evaluate("(()=>{const n=document.querySelector('#inline-message');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(n,'M3 synthetic draft; do not send');n.dispatchEvent(new Event('input',{bubbles:true}));})()");
  check('Unmocked unavailable state retains draft and blocks send', await b.evaluate("document.querySelector('#inline-message').value==='M3 synthetic draft; do not send'&&document.querySelector('.composer .press-button').disabled"));
  await b.evaluate("document.querySelector('.account-trigger').click()");
  await b.wait("document.querySelector('dialog[open] .auth-unavailable')");
  check('Unmocked account sidebar exposes unavailable auth, not a simulated login', await b.evaluate("document.querySelectorAll('.auth-unavailable button:disabled').length===3&&!document.querySelector('input[type=password]')"));
  await b.screenshot(`${output}/account-desktop.png`);
  await b.send('Emulation.setDeviceMetricsOverride', { width:320, height:760, deviceScaleFactor:1, mobile:false });
  await b.screenshot(`${output}/account-mobile.png`);
  check('Unmocked 320px drawer fits the viewport', await b.evaluate("document.querySelector('.account-drawer').getBoundingClientRect().right<=320&&document.documentElement.scrollWidth<=320"));
  await route('/account'); await b.wait("document.querySelector('#profile-phone')");
  check('Unmocked profile is explicitly a guest hint, with no authenticated customer claim', await b.evaluate("document.querySelector('.account-form').textContent.includes('không phải tài khoản')&&document.querySelector('#profile-phone').value===''"));
  await route('/orders/DEMO-M3-UNKNOWN');
  await b.wait("document.querySelector('.purchase-page')?.textContent.includes('Không tìm thấy đơn demo')");
  check('Unmocked unknown order never displays a fabricated real receipt', await b.evaluate("!document.querySelector('.success-banner')"));
  await route('/products/SKU-AP-X');
  check('Unmocked PDP uses the exact BTC SKU and honest image/snapshot state', await b.evaluate("document.querySelector('.product-detail').dataset.sku==='SKU-AP-X'&&document.querySelector('.pdp-info .price').textContent==='4.890.000₫'&&document.querySelector('.pdp-gallery').textContent.includes('Chưa có ảnh')&&document.querySelector('.demo-notice').textContent.includes('Không tạo đơn thật')"));
  check('Unmocked probe made health GETs only, with no service mutations', requests.length > 0 && requests.every(r => r.method === 'GET' && r.url.endsWith('/health')));
  await writeFile(`${output}/results.json`, JSON.stringify({ checks, requests, backend:'unavailable; no live processing verified' }, null, 2));
  console.log(`${checks.length} unmocked availability/UI checks passed.`);
} finally { await b.close(); }
