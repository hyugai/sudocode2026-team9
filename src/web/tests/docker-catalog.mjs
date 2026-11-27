// Opt-in integration check: run against a started Compose web container.
import assert from "node:assert/strict";
import { test } from "node:test";

const base = process.env.WEB_BASE_URL || "http://localhost:3000";

function findProps(value, field) {
  if (!value || typeof value !== "object") return;
  if (Object.hasOwn(value, field)) return value;
  for (const child of Object.values(value)) {
    const found = findProps(child, field);
    if (found) return found;
  }
}

function pageProps(html, field) {
  // SessionProviders waits for browser auth before mounting Storefront. Its
  // server-fetched props are in the Flight payload rather than static cards.
  let flight = "";
  for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
    const push = script[1].match(/^self\.__next_f\.push\(([\s\S]*)\)$/);
    if (!push) continue;
    const chunk = JSON.parse(push[1]);
    if (chunk[0] === 1) flight += chunk[1];
  }
  for (const line of flight.split("\n")) {
    let value;
    try { value = JSON.parse(line.slice(line.indexOf(":") + 1)); }
    catch { continue; } // Import/module hints are not JSON model rows.
    const props = findProps(value, field);
    if (props) return props;
  }
  assert.fail(`Page did not include ${field} for the browser`);
}

test("Storefront sends the live backend catalog and product details to the browser", async () => {
  const catalogResponse = await fetch(new URL("/api/catalog/products", base));
  assert.equal(catalogResponse.status, 200);
  const catalog = await catalogResponse.json();
  assert.ok(Array.isArray(catalog.items) && catalog.items.length > 0, "Backend catalog is empty");

  const page = await fetch(new URL("/", base));
  assert.equal(page.status, 200);
  const html = await page.text();
  const props = pageProps(html, "catalogProducts");
  assert.equal(props.catalogError, false, "Storefront failed to load the catalog");
  assert.deepEqual(props.catalogProducts.map(item => item.id).sort(), catalog.items.map(item => item.sku).sort(),
    "Storefront must receive every backend product, even when the page returns HTTP 200");

  const sku = catalog.items[0].sku;
  const detail = await fetch(new URL(`/products/${encodeURIComponent(sku)}`, base));
  assert.equal(detail.status, 200);
  assert.equal(pageProps(await detail.text(), "product").product.sku, sku,
    "Product detail must load its live backend record");
});
