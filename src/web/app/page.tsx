import Storefront from "./components/storefront";
import { productCards, type ProductCard } from "@/utils/catalog";
import { getLiveProducts } from "@/utils/live-catalog";

export default async function Page({ searchParams }: { searchParams: Promise<{ q?: string | string[]; category?: string | string[] }> }) {
  const { q, category } = await searchParams;
  let catalogProducts: ProductCard[] = [];
  let catalogError = false;
  try {
    catalogProducts = productCards(await getLiveProducts());
  } catch (error) {
    console.error("Unable to load catalog from backend", error);
    catalogError = true;
  }
  return <Storefront key={`${q ?? ""}-${category ?? ""}`} initialSearch={typeof q === "string" ? q : ""} initialCategory={typeof category === "string" ? category : undefined} catalogProducts={catalogProducts} catalogError={catalogError} />;
}
