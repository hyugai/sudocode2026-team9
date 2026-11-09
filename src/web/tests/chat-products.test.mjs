import assert from "node:assert/strict";
import test from "node:test";
import { loadChatCatalog, matchChatProducts } from "../utils/chat-products.ts";
import { productHref } from "../utils/catalog.ts";
import { productIllustrationFor } from "../utils/product-illustrations.ts";

const product = (overrides = {}) => ({
  sku: "SKU-AP-X", name: "Máy lọc không khí AirPure X", brand: "AirPure",
  category: "gia-dung/may-loc-khong-khi", list_price_vnd: 1234567, attributes: {}, stock: 5, variants: [], ...overrides,
});

test("known SKU or DB product/model name yields one card with catalog price, image and link", () => {
  for (const text of ["Chọn `sku-ap-x`.", "Máy lọc không khí AirPure X phù hợp.", "So sánh **AIRPURE X** nhé.", "may loc khong khi airpure x"]) {
    const cards = matchChatProducts(text, [product()]);
    assert.equal(cards.length, 1);
    assert.equal(cards[0].price, 1234567);
    assert.equal(cards[0].name, product().name);
    assert.ok(productIllustrationFor(cards[0].productSku));
    assert.equal(productHref(cards[0].productSku), "/products/SKU-AP-X");
  }
  assert.equal(matchChatProducts("AirPure X (SKU-AP-X), SKU-AP-X giá 1 đồng", [product()]).length, 1);
});

test("unknown products and SKU prefixes do not produce invented cards", () => {
  assert.deepEqual(matchChatProducts("SKU-AP-X-FAKE và AirPure", [product()]), []);
  const old = product({ sku: "SKU-AP-X-2024", name: "Máy lọc không khí AirPure X 2024" });
  assert.deepEqual(matchChatProducts("AirPure X 2024", [product(), old]).map(card => card.sku), [old.sku]);
  assert.deepEqual(matchChatProducts("SKU-AP-X-2024", [product(), old]).map(card => card.sku), [old.sku]);
});

test("variant SKU uses its DB price delta and parent product image/link", () => {
  const item = product({ stock: 0, variants: [
    { variant_sku: "SKU-AP-X-DEN", color: "Đen", size: "M", price_delta_vnd: 50000, stock: 3 },
    { variant_sku: "SKU-AP-X-TRANG", color: "Trắng", size: "M", price_delta_vnd: 100000, stock: 0 },
  ] });
  const [card] = matchChatProducts("AirPure X, chọn SKU-AP-X-DEN", [item]);
  assert.equal(card.sku, "SKU-AP-X-DEN");
  assert.equal(card.productSku, "SKU-AP-X");
  assert.equal(card.price, 1284567);
  assert.equal(card.fromPrice, false);
  assert.equal(card.unavailable, false);
  const [base] = matchChatProducts("AirPure X", [item]);
  assert.equal(base.fromPrice, true);
  assert.equal(base.price, 1284567);
  assert.equal(base.unavailable, false);
});

test("card data comes from catalog API and no static catalog is substituted on failure", async () => {
  const calls = [];
  const catalog = await loadChatCatalog(async (url, options) => {
    calls.push({ url, options });
    return Response.json({ items: [product({ list_price_vnd: 9876543 })] });
  });
  assert.equal(calls[0].url, "/api/catalog/products");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(matchChatProducts("SKU-AP-X", catalog)[0].price, 9876543);
  await assert.rejects(loadChatCatalog(async () => Response.json({}, { status: 503 })));
  assert.deepEqual(matchChatProducts("SKU-AP-X", []), []);
});
