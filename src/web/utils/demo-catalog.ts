import btcCatalog from "../data/products.json" with { type: "json" };
import { productCards } from "./catalog.ts";

export const catalogReferenceDate = btcCatalog.reference_date;

export function getProductDetails(sku: string) {
  return btcCatalog.products.find(product => product.sku === sku);
}

export type ProductDetails = NonNullable<ReturnType<typeof getProductDetails>>;
export const products = productCards(btcCatalog.products);
