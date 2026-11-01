import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { connect } from "./browser-support.mjs";

const base = process.env.BASE_URL || "http://127.0.0.1:3100";
const fixture = process.env.CATALOG_FIXTURE_URL || "http://127.0.0.1:8100";
const output = process.env.BROWSER_ARTIFACT_DIR || "/tmp/synee-live-catalog";
await mkdir(output, { recursive: true });
const b = await connect();
const setCatalog = async state => {
  const response = await fetch(`${fixture}/__test/catalog`, { method: "POST", body: JSON.stringify(state) });
  assert.ok(response.ok);
};
const check = async (name, expression) => {
  assert.ok(await b.evaluate(expression), name);
  console.log("PASS", name);
};
const route = async path => {
  await b.send("Page.navigate", { url: base + path });
  await b.wait("document.querySelector('.site-header') && document.querySelector('.mode-toggle button:last-child') && !document.querySelector('.mode-toggle button:last-child').disabled");
};

try {
  await b.send("Page.enable");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, options) => {
      const url = String(input);
      if (url.endsWith('/health')) return Response.json({ status: 'ok' });
      if (url.endsWith('/api/voice/capabilities')) return Response.json({ enabled: false });
      return originalFetch(input, options);
    };
  ` });
  await setCatalog({ price: 1234567 });
  await route("/");
  await b.wait("document.querySelectorAll('.product-card').length === 40");
  await check("Storefront uses the backend API price rather than the bundled demo snapshot", "document.querySelector('[data-sku=SKU-AP-X] .price').textContent === '1.234.567₫'");
  await b.screenshot(`${output}/catalog-desktop.png`);
  await b.evaluate("document.querySelector('[data-sku=SKU-AP-X]').click()");
  await b.wait("document.querySelector('.product-detail')");
  await check("Product details preserve the live API price and do not route live products into demo checkout", "document.querySelector('.pdp-info .price').textContent === '1.234.567₫' && !document.querySelector('.pdp-purchase-actions') && !!document.querySelector('.pdp-ask')");
  await b.evaluate("document.querySelector('.pdp-ask').click()");
  await b.wait("document.querySelector('#floating-message')");
  await check("Live SKU context reaches the shared chat", "document.querySelector('.consultation-context').textContent.includes('SKU-AP-X') && document.querySelector('.consultation-context').textContent.includes('1.234.567₫')");
  await b.evaluate("document.querySelector('.mode-toggle button:last-child').click()");
  await b.wait("document.querySelector('.voice-wave')");
  await check("LiveKit Wave remains available from live product consultation", "!!document.querySelector('dialog[open] .voice-wave[data-lk-state=disconnected]')");
  await b.screenshot(`${output}/live-product-voice.png`);
  await b.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 760, deviceScaleFactor: 1, mobile: false });
  await check("Live catalog and Voice dialog fit 320px", "document.documentElement.scrollWidth <= 320 && document.querySelector('dialog').scrollWidth <= document.querySelector('dialog').clientWidth");
  await b.evaluate("document.querySelector('dialog[open] .dialog-header button').click()");
  await setCatalog({ unavailable: true });
  await route("/");
  await b.wait("document.querySelector('.empty-catalog[role=alert]')");
  await check("Catalog outage shows an error without substituting demo cards or disabling Voice", "document.querySelectorAll('.product-card').length === 0 && !document.querySelector('.mode-toggle button:last-child').disabled");
  await setCatalog({});
  await route("/");
  await b.wait("document.querySelectorAll('.product-card').length === 40");
  await check("Catalog recovers on reload", "!document.querySelector('.empty-catalog[role=alert]')");
  const missing = await fetch(base + "/products/SKU-NOT-IN-CATALOG");
  assert.equal(missing.status, 404);
  console.log("PASS Unknown live SKU returns 404");
} finally {
  await setCatalog({});
  await b.close();
}
