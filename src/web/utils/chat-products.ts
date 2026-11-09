import type { LiveProductDetails } from "./catalog.ts";

export type ChatProduct = {
  sku: string; productSku: string; name: string; price: number;
  fromPrice: boolean; variantLabel: string; unavailable: boolean;
};

export async function loadChatCatalog(fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<LiveProductDetails[]> {
  const response = await fetcher("/api/catalog/products", { cache: "no-store", signal });
  if (!response.ok) throw new Error("Chưa tải được danh mục sản phẩm.");
  const data = await response.json();
  if (!Array.isArray(data?.items)) throw new Error("Danh mục sản phẩm không hợp lệ.");
  return data.items;
}

const fold = (text: string) => text.toLocaleLowerCase("vi").normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/g, "d").replace(/\s+/g, " ").trim();
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Match known catalog identities, with longer names winning overlapping mentions. */
export function matchChatProducts(text: string, catalog: readonly LiveProductDetails[]): ChatProduct[] {
  const source = fold(text);
  type Mention = { product: LiveProductDetails; variant?: LiveProductDetails["variants"][number]; start: number; end: number; code: boolean };
  const mentions: Mention[] = [];
  for (const product of catalog) {
    const name = fold(product.name);
    const brand = fold(product.brand);
    const brandAt = brand ? name.indexOf(brand) : -1;
    // Model names such as "AirPure X" come from the canonical DB name/brand.
    const modelName = brandAt >= 0 ? name.slice(brandAt) : "";
    const names = new Set([name, ...(modelName && modelName !== brand ? [modelName] : [])]);
    const terms = [
      { text: product.sku, code: true, variant: undefined },
      ...product.variants.map(variant => ({ text: variant.variant_sku, code: true, variant })),
      ...[...names].map(text => ({ text, code: false, variant: undefined })),
    ];
    for (const term of terms) {
      const value = fold(term.text);
      if (!value) continue;
      const boundary = term.code ? "\\p{L}\\p{N}_-" : "\\p{L}\\p{N}";
      const pattern = new RegExp(`(^|[^${boundary}])(${escape(value)})(?![${boundary}])`, "gu");
      for (const match of source.matchAll(pattern)) {
        const start = match.index + match[1].length;
        mentions.push({ product, variant: term.variant, start, end: start + value.length, code: term.code });
      }
    }
  }
  const named = mentions.filter(item => !item.code);
  const matches = mentions.filter(item => item.code || !named.some(other =>
    other.start <= item.start && other.end >= item.end && other.end - other.start > item.end - item.start));
  const variantProducts = new Set(matches.filter(item => item.variant).map(item => item.product.sku));
  const seen = new Set<string>();
  return matches.sort((a, b) => a.start - b.start).flatMap(({ product, variant }) => {
    if (variantProducts.has(product.sku) && !variant) return [];
    const sku = variant?.variant_sku ?? product.sku;
    if (seen.has(sku)) return [];
    seen.add(sku);
    const delta = variant?.price_delta_vnd ?? (product.variants.length ? Math.min(...product.variants.map(item => item.price_delta_vnd)) : 0);
    const stock = variant?.stock ?? (product.variants.length ? product.variants.reduce((total, item) => total + item.stock, 0) : product.stock);
    return [{ sku, productSku: product.sku, name: product.name, price: product.list_price_vnd + delta,
      fromPrice: !variant && product.variants.length > 0,
      variantLabel: variant ? [variant.color, variant.size].filter(Boolean).join(" · ") : "",
      unavailable: product.attributes.discontinued === true || stock <= 0 }];
  });
}
