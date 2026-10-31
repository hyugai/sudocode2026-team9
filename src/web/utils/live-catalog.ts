import "server-only";

import type { LiveProductDetails } from "./catalog";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || (
  process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://telesale-agent-api.onrender.com"
)).replace(/\/$/, "");

async function catalogResponse(path: string) {
  const response = await fetch(`${apiBase}/api/catalog/products${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Catalog API returned HTTP ${response.status}`);
  return response.json() as Promise<unknown>;
}

export async function getLiveProducts(): Promise<LiveProductDetails[]> {
  const data = await catalogResponse("");
  if (!data || typeof data !== "object" || !("items" in data) || !Array.isArray(data.items)) {
    throw new Error("Catalog API returned an invalid product list");
  }
  return data.items as LiveProductDetails[];
}

export async function getLiveProduct(sku: string): Promise<LiveProductDetails | null> {
  const response = await fetch(`${apiBase}/api/catalog/products/${encodeURIComponent(sku)}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Catalog API returned HTTP ${response.status}`);
  const product: unknown = await response.json();
  if (!product || typeof product !== "object" || !("sku" in product) || product.sku !== sku) {
    throw new Error("Catalog API returned an invalid product");
  }
  return product as LiveProductDetails;
}
