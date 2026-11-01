// Local-only catalog API fixture for SSR/browser regressions. No database or LLM.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

const catalog = JSON.parse(await readFile(new URL("../data/products.json", import.meta.url)));
let unavailable = false;
let overridePrice = null;
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const send = (status, body) => {
    response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify(body));
  };
  if (url.pathname === "/__test/catalog" && request.method === "POST") {
    let body = "";
    for await (const chunk of request) body += chunk;
    const state = JSON.parse(body || "{}");
    unavailable = state.unavailable === true;
    overridePrice = Number.isSafeInteger(state.price) ? state.price : null;
    return send(200, { status: "updated" });
  }
  if (url.pathname === "/health") return send(200, { status: "ok" });
  if (!url.pathname.startsWith("/api/catalog/products")) return send(404, { detail: "Not found" });
  if (unavailable) return send(503, { detail: "Catalog is unavailable" });
  const products = catalog.products.map(product => product.sku === "SKU-AP-X" && overridePrice !== null
    ? { ...product, list_price_vnd: overridePrice } : product);
  if (url.pathname === "/api/catalog/products") return send(200, { items: products });
  const sku = decodeURIComponent(url.pathname.slice("/api/catalog/products/".length));
  const product = products.find(item => item.sku === sku);
  return send(product ? 200 : 404, product || { detail: "Product not found" });
});

server.listen(Number(process.env.CATALOG_FIXTURE_PORT || 8100), "127.0.0.1", () => {
  console.log(`Catalog fixture ready at http://127.0.0.1:${server.address().port}`);
});
