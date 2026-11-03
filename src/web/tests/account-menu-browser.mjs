// Start Next.js plus a Chromium CDP session before running this suite.
// Uses synthetic guest data and never calls live authentication/CRM services.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { connect } from "./browser-support.mjs";

const b = await connect();
const base = process.env.BASE_URL || "http://127.0.0.1:3000";
const output = process.env.BROWSER_ARTIFACT_DIR || fileURLToPath(new URL("../../../outputs/debug/streaming-ui/account-menu/", import.meta.url));
await mkdir(output, { recursive: true });
const checks = [];
const check = async (name, expression) => { assert.ok(await b.evaluate(expression), name); checks.push(name); console.log("PASS", name); };
const click = selector => b.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); element.focus(); element.click(); })()`);
const type = (selector, value) => b.evaluate(`(() => {
  const input = document.querySelector(${JSON.stringify(selector)});
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
const key = async (keyValue, code, virtualCode) => {
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: keyValue, code, windowsVirtualKeyCode: virtualCode });
  await b.send("Input.dispatchKeyEvent", { type: "keyUp", key: keyValue, code, windowsVirtualKeyCode: virtualCode });
};
const open = async () => {
  await click(".account-trigger");
  await b.wait("!!document.querySelector('.account-popover')");
};
const saved = "JSON.parse(sessionStorage.getItem('synee.guest.conversation.v1'))";

try {
  await b.send("Page.enable");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    if (!sessionStorage.getItem('account-menu.seeded')) {
      sessionStorage.clear(); sessionStorage.setItem('account-menu.seeded', '1');
      sessionStorage.setItem('synee.guest.conversation.v1', JSON.stringify({ version: 1,
        sessionId: '10000000-0000-4000-8000-000000000001', input: 'Bản nháp cần được giữ', customerPhone: '0901234567', voicePreview: false, consultation: null,
        messages: [{ role: 'agent', text: 'Mình là Synee AI.' }, { role: 'user', text: 'Mình muốn được tư vấn tai nghe.' }, { role: 'agent', text: 'Mình sẽ hỗ trợ bạn.' }] }));
    }
    window.__requests = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options = {}) => {
      const url = String(input);
      if (url.endsWith('/health')) return Promise.resolve(Response.json({ status: 'ok' }));
      if (url.includes('/api/') && options.method && options.method !== 'GET') {
        __requests.push({ url, method: options.method });
        return Promise.resolve(Response.json({ detail: 'Unexpected service mutation' }, { status: 503 }));
      }
      return originalFetch(input, options);
    };
  ` });
  await b.send("Page.navigate", { url: base });
  await b.wait(`document.querySelector('.account-trigger') && document.querySelector('.mode-toggle button:last-child') && !document.querySelector('.mode-toggle button:last-child').disabled && ${saved}?.customerPhone === '0901234567'`);
  await b.evaluate("document.fonts.ready");
  await open();
  await check("Account opens a compact menu immediately below its trigger", "(() => { const panel = document.querySelector('.account-popover').getBoundingClientRect(), trigger = document.querySelector('.account-trigger').getBoundingClientRect(); return panel.width === 248 && panel.height < 320 && Math.abs(panel.right - trigger.right) < 1 && panel.top >= trigger.bottom && panel.top - trigger.bottom <= 10 && !document.querySelector('dialog[open]'); })()");
  await check("Menu contains profile, orders, history and guest logout", "document.querySelectorAll('.account-popover a').length === 3 && !!document.querySelector('.account-popover a[href=\"/account\"]') && !!document.querySelector('.account-popover a[href=\"/orders\"]') && !!document.querySelector('.account-popover a[href=\"/account/conversations\"]') && document.querySelector('.account-popover button').textContent.includes('Đăng xuất')");
  await check("Guest logout is disabled with an associated explanation", "(() => { const button = document.querySelector('.account-popover button'); return button.disabled && document.getElementById(button.getAttribute('aria-describedby')).textContent.includes('Phiên khách'); })()");
  await b.screenshot(`${output}/after-desktop.png`);
  await click(".account-trigger");
  await b.wait("!document.querySelector('.account-popover')");
  await check("Repeated click closes the account menu without changing guest data", `${saved}.input === 'Bản nháp cần được giữ' && __requests.length === 0`);
  await open();
  await b.send("Input.dispatchMouseEvent", { type: "mousePressed", x: 32, y: 200, button: "left", clickCount: 1 });
  await b.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: 32, y: 200, button: "left", clickCount: 1 });
  await b.wait("!document.querySelector('.account-popover')");
  await check("Outside click dismisses the menu without opening a blocking dialog", "!document.querySelector('dialog[open]') && document.querySelector('.account-trigger').getAttribute('aria-expanded') === 'false'");
  await open();
  await key("ArrowDown", "ArrowDown", 40);
  await b.wait("document.activeElement === document.querySelector('.account-popover a')");
  await key("Escape", "Escape", 27);
  await b.wait("!document.querySelector('.account-popover') && document.activeElement === document.querySelector('.account-trigger')");
  await check("Arrow Down opens links for keyboard use and Escape restores trigger focus", `${saved}.sessionId === '10000000-0000-4000-8000-000000000001' && __requests.length === 0`);
  await open();
  await click(".account-popover a[href='/account']");
  await b.wait("location.pathname === '/account' && document.querySelector('#profile-phone')?.value === '0901234567'");
  await check("Profile opens its existing page and closes the compact menu", "!document.querySelector('.account-popover') && !!document.querySelector('.profile-avatar-panel')");
  await type("#profile-phone", "khong-hop-le");
  await click(".save-profile");
  await b.wait("document.querySelector('.account-form [role=alert]')?.textContent.includes('Việt Nam')");
  await check("Invalid profile input does not change the stored identity", `${saved}.customerPhone === '0901234567' && document.querySelector('#profile-phone').getAttribute('aria-invalid') === 'true'`);
  await type("#profile-phone", "0901234567");
  await click(".save-profile");
  await b.wait("document.querySelector('.profile-save [role=status]')?.textContent.includes('Đã lưu')");
  await check("Saving unchanged identity keeps the draft and conversation", `${saved}.input === 'Bản nháp cần được giữ' && ${saved}.sessionId === '10000000-0000-4000-8000-000000000001'`);
  await type("#profile-phone", "0909999999");
  await click(".save-profile");
  await b.wait("document.querySelector('.account-form [role=alert]')?.textContent.includes('Xác nhận')");
  await check("Changing identity requires explicit confirmation", `${saved}.customerPhone === '0901234567' && ${saved}.input === 'Bản nháp cần được giữ'`);
  await click(".confirm-profile-reset");
  await click(".save-profile");
  await b.wait(`${saved}.customerPhone === '0909999999'`);
  await check("Confirmed profile save starts a clean conversation and updates the sidebar", `${saved}.sessionId === '' && ${saved}.input === '' && document.querySelector('.account-page-sidebar .account-identity').textContent.includes('0909999999')`);
  await b.screenshot(`${output}/profile-desktop.png`);
  await open();
  await check("Page and account menu have unique IDs and linked controls", "(() => { const ids = [...document.querySelectorAll('[id]')].map(element => element.id), trigger = document.querySelector('.account-trigger'); return new Set(ids).size === ids.length && document.getElementById(trigger.getAttribute('aria-controls')) === document.querySelector('.account-popover'); })()");
  await click(".account-popover a[href='/orders']");
  await b.wait("location.pathname === '/orders' && !!document.querySelector('.purchase-page')");
  await check("Orders link closes the menu and opens the existing orders page", "!document.querySelector('.account-popover') && document.querySelector('.purchase-page h1').textContent.includes('Đơn hàng') && __requests.length === 0");
  await open();
  await check("Orders is marked as the current section", "document.querySelector('.account-popover a[href=\"/orders\"]').getAttribute('aria-current') === 'page'");
  await click(".account-popover a[href='/account/conversations']");
  await b.wait("location.pathname === '/account/conversations' && !!document.querySelector('.account-history')");
  await check("History opens from the compact menu", "!document.querySelector('.account-popover') && !!document.querySelector('.account-history')");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
  await open();
  await check("Mobile menu stays below the account button within 320px", "(() => { const panel = document.querySelector('.account-popover'), rect = panel.getBoundingClientRect(), trigger = document.querySelector('.account-trigger').getBoundingClientRect(); return rect.left >= 0 && rect.right <= innerWidth && rect.top >= trigger.bottom && rect.bottom <= innerHeight && rect.height < 320 && document.documentElement.scrollWidth <= innerWidth && [...panel.querySelectorAll('span')].every(label => label.getBoundingClientRect().width > 0); })()");
  await b.screenshot(`${output}/after-mobile.png`);
  await b.evaluate("document.querySelector('.account-popover a:last-of-type').focus()");
  await key("Tab", "Tab", 9);
  await b.wait("!document.querySelector('.account-popover')");
  await check("Tab leaves the nonmodal menu and dismisses it", "document.querySelector('.account-trigger').getAttribute('aria-expanded') === 'false' && !document.querySelector('dialog[open]')");
  await open();
  await click(".account-popover a[href='/account']");
  await b.wait("location.pathname === '/account' && !!document.querySelector('#profile-phone')");
  await check("Mobile profile fields and avatar wrap without horizontal scrolling", "document.documentElement.scrollWidth <= innerWidth && document.querySelector('#profile-phone').getBoundingClientRect().right <= innerWidth && document.querySelector('.profile-avatar-panel').getBoundingClientRect().right <= innerWidth");
  await b.evaluate("document.querySelector('.account-form').scrollIntoView({ block: 'start', behavior: 'instant' })");
  await b.screenshot(`${output}/profile-mobile.png`);
  await b.send("Page.reload");
  await b.wait("document.querySelector('#profile-phone')?.value === '0909999999'");
  await check("Saved profile restores after reload without service mutations", "__requests.length === 0");
  await writeFile(`${output}/results.json`, JSON.stringify({ checks }, null, 2));
  console.log("Account menu regression complete");
} finally { await b.close(); }
