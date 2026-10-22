import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { applianceSubcategories, categoryFor, filterProducts, getProductDetails, productHref, products } from "../utils/catalog.ts";

const source = JSON.parse(await readFile(new URL("../../../dataset/BTC-Data-Vong1-TEAMS/catalog/products.json", import.meta.url)));

test("Every card URL resolves to the exact unmodified BTC SKU record", () => {
  for (const product of source.products) {
    assert.equal(productHref(product.sku), `/products/${encodeURIComponent(product.sku)}`);
    assert.deepEqual(getProductDetails(product.sku), product);
  }
  assert.equal(getProductDetails("SKU-DOES-NOT-EXIST"), undefined);
  assert.equal(getProductDetails("sku-ap-x"), undefined);
  assert.equal(productHref("A/B C"), "/products/A%2FB%20C");
});

test("Every source SKU maps once, retaining its name, category path and list price", () => {
  assert.equal(products.length, source.products.length);
  assert.equal(new Set(products.map(p => p.id)).size, source.products.length);
  for (const record of source.products) {
    const mapped = products.find(p => p.id === record.sku);
    assert.equal(mapped.name, record.name);
    assert.equal(mapped.sourceCategory, record.category);
    assert.equal(mapped.price, `${new Intl.NumberFormat("vi-VN").format(record.list_price_vnd)}₫`);
    assert.ok(mapped.category, record.sku);
    for (const variant of record.variants) {
      assert.ok(variant.variant_sku);
      assert.equal(categoryFor(record.category), mapped.category);
    }
  }
});

test("The appliance parent contains the three exact BTC subcategory sets", () => {
  for (const subcategory of applianceSubcategories) {
    const expected = source.products.filter(p => p.category === subcategory.sourceCategory).map(p => p.sku);
    assert.deepEqual(filterProducts("Điện gia dụng", subcategory.name, "").map(p => p.id), expected);
  }
  assert.equal(filterProducts("Điện gia dụng", "", "").length, 18);
  assert.equal(filterProducts("Điện gia dụng", "Máy lọc không khí", "").length, 8);
  assert.equal(filterProducts("Điện gia dụng", "Máy lọc nước", "").length, 3);
  assert.equal(filterProducts("Điện gia dụng", "Nồi chiên", "").length, 3);
  assert.equal(categoryFor("gia-dung/phu-kien"), "Phụ kiện");
  assert.equal(categoryFor("thoi-trang/phu-kien"), "Phụ kiện");
  assert.equal(categoryFor("unknown"), undefined);
});

test("Search intersects category selection; resetting and empty results are deterministic", () => {
  assert.deepEqual(filterProducts("Điện gia dụng", "Máy lọc nước", " ro9 ").map(p => p.id), ["SKU-WF-RO9"]);
  assert.equal(filterProducts("Điện gia dụng", "Nồi chiên", "AirPure").length, 0);
  assert.equal(filterProducts("Thời trang", "Máy lọc nước", "").length, 7);
  assert.equal(filterProducts("Tất cả", "", "").length, 40);
  const first = filterProducts("Tất cả", "", "");
  first.reverse();
  assert.equal(products[0].id, source.products[0].sku);
});
