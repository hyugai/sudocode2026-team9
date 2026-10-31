import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { connect } from "./browser-support.mjs";

const browser = await connect();
const output = process.env.BROWSER_ARTIFACT_DIR || "/tmp/synee-categories";
await mkdir(output, { recursive: true });
const checks = [];
const check = (name, result) => { assert.ok(result, name); checks.push(name); console.log("PASS", name); };
const choose = async (selector, label) => {
  await browser.evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].find(n=>n.textContent===${JSON.stringify(label)}).click()`);
};
try {
  await browser.send("Page.enable");
  await browser.send("Emulation.setScrollbarsHidden", { hidden: true });
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.send("Page.navigate", { url: process.env.BASE_URL || "http://localhost:3000" });
  await browser.wait("document.querySelector('.category-nav button')");
  await browser.evaluate("document.fonts.ready");
  await browser.wait("document.querySelector('.category-nav button')&&Object.keys(document.querySelector('.category-nav button')).some(k=>k.startsWith('__reactProps'))");
  await browser.evaluate("document.querySelector('#catalog').scrollIntoView({behavior:'instant'})");
  if (process.argv.includes("--capture-before")) {
    await browser.screenshot(`${output}/before-desktop.png`);
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
    await browser.screenshot(`${output}/before-mobile.png`);
  } else {
    check("Five top-level categories", await browser.evaluate("document.querySelectorAll('.category-nav button').length===5"));
    const total = await browser.evaluate("document.querySelectorAll('.product-card').length");
    await choose(".category-nav button", "Điện gia dụng");
    await browser.wait("document.querySelector('.subcategory-nav')");
    check("Parent shows all 18 appliances including fans and bundle", await browser.evaluate("document.querySelectorAll('.product-card').length===18"));
    const sizes = await browser.evaluate("[...document.querySelectorAll('.category-nav button')].map(n=>n.getBoundingClientRect().width)");
    check("Desktop categories evenly fill the 1200px row", sizes.every(n => Math.abs(n - 240) < 1));
    await browser.wait("[...document.querySelectorAll('.category-nav img')].every(n=>n.complete&&n.naturalWidth>0)");
    check("All category icons render at 20px", await browser.evaluate("[...document.querySelectorAll('.category-nav img')].every(n=>n.getBoundingClientRect().width===20&&n.getBoundingClientRect().height===20)"));
    await browser.screenshot(`${output}/after-desktop.png`);
    for (const [name, count] of [["Máy lọc không khí", 8], ["Máy lọc nước", 3], ["Nồi chiên", 3]]) {
      await choose(".subcategory-nav button", name);
      await browser.wait(`document.querySelectorAll('.product-card').length===${count}`);
      check(`${name} filters ${count} BTC SKUs`, await browser.evaluate(`[...document.querySelectorAll('.product-card')].every(n=>n.dataset.subcategory===${JSON.stringify(name)})`));
    }
    await choose(".category-nav button", "Thời trang");
    check("Switching parent clears and hides the subcategory", await browser.evaluate("!document.querySelector('.subcategory-nav')&&document.querySelectorAll('.product-card').length===7"));
    await choose(".category-nav button", "Điện gia dụng");
    check("Returning to appliances resets the subcategory", await browser.evaluate("document.querySelector('.subcategory-nav button').getAttribute('aria-pressed')==='true'&&document.querySelectorAll('.product-card').length===18"));
    await choose(".subcategory-nav button", "Máy lọc nước");
    await browser.evaluate("(()=>{const n=document.querySelector('#product-search');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(n,'RO9');n.dispatchEvent(new Event('input',{bubbles:true}));})()");
    await browser.evaluate("document.querySelector('.product-search').requestSubmit()");
    await browser.wait("document.querySelectorAll('.product-card').length===1");
    check("Search intersects the subcategory by SKU", await browser.evaluate("document.querySelector('.product-card').dataset.sku==='SKU-WF-RO9'"));
    await choose(".filter-status button", "Xóa bộ lọc");
    check("Clear restores the full catalog", await browser.evaluate(`!document.querySelector('.subcategory-nav')&&document.querySelectorAll('.product-card').length===${total}`));
    await choose(".category-nav button", "Điện gia dụng");
    await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate("document.querySelector('#catalog').scrollIntoView({behavior:'instant'})");
    check("320px layout does not overflow the page", await browser.evaluate("document.documentElement.scrollWidth<=320"));
    await browser.evaluate("[...document.querySelectorAll('.subcategory-nav button')].at(-1).focus()");
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13 });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await browser.wait("document.querySelectorAll('.product-card').length===3");
    check("Keyboard activates the offscreen subcategory", await browser.evaluate("document.activeElement.textContent==='Nồi chiên'&&document.activeElement.getAttribute('aria-pressed')==='true'&&document.activeElement.getBoundingClientRect().right<=320"));
    await browser.screenshot(`${output}/after-mobile.png`);
    await browser.evaluate("document.querySelector('.cart-link').click()");
    await browser.wait("document.querySelector('.purchase-page')?.dataset.view==='cart'");
    check("Header opens the implemented demo cart", await browser.evaluate("document.querySelector('.purchase-page').textContent.includes('Mua sắm mô phỏng')"));
    await writeFile(`${output}/results.json`, JSON.stringify({ checks, total }, null, 2));
  }
} finally { await browser.close(); }
