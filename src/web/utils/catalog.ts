import btcCatalog from "../../../dataset/BTC-Data-Vong1-TEAMS/catalog/products.json" with { type: "json" };

export const categories = [
  { name: "Tất cả", icon: "category-bag.svg" },
  { name: "Điện gia dụng", icon: "category-appliance.svg" },
  { name: "Thời trang", icon: "category-shirt.svg" },
  { name: "Mẹ & bé", icon: "category-bag.svg" },
  { name: "Phụ kiện", icon: "category-bag.svg" },
] as const;

export const applianceSubcategories = [
  { name: "Máy lọc không khí", sourceCategory: "gia-dung/may-loc-khong-khi" },
  { name: "Máy lọc nước", sourceCategory: "gia-dung/may-loc-nuoc" },
  { name: "Nồi chiên", sourceCategory: "gia-dung/noi-chien" },
] as const;

/** Display-only hierarchy: original BTC records and category paths stay intact. */
export function categoryFor(sourceCategory: string): string | undefined {
  if (sourceCategory.endsWith("/phu-kien")) return "Phụ kiện";
  if (sourceCategory.startsWith("gia-dung/")) return "Điện gia dụng";
  if (sourceCategory.startsWith("thoi-trang/")) return "Thời trang";
  if (sourceCategory === "me-be") return "Mẹ & bé";
}

export const catalogReferenceDate = btcCatalog.reference_date;

export function getProductDetails(sku: string) {
  return btcCatalog.products.find(product => product.sku === sku);
}

export type ProductDetails = NonNullable<ReturnType<typeof getProductDetails>>;

export function productHref(sku: string) {
  return `/products/${encodeURIComponent(sku)}`;
}

// BTC supplies no product photos, sales counts, ratings or publication dates.
// Do not reuse unrelated demonstration images or fabricate those fields.
export const products = btcCatalog.products.map(product => ({
  id: product.sku,
  name: product.name,
  price: `${new Intl.NumberFormat("vi-VN").format(product.list_price_vnd)}₫`,
  category: categoryFor(product.category),
  sourceCategory: product.category,
  subcategory: applianceSubcategories.find(c => c.sourceCategory === product.category)?.name,
}));

export function filterProducts(category: string, subcategory: string, search: string) {
  const query = search.trim().toLocaleLowerCase("vi");
  return products.filter(product =>
    (category === "Tất cả" || product.category === category) &&
    (category !== "Điện gia dụng" || !subcategory || product.subcategory === subcategory) &&
    `${product.name} ${product.id}`.toLocaleLowerCase("vi").includes(query)
  );
}
