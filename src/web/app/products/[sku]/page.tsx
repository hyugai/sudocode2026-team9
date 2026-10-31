import { notFound } from "next/navigation";
import Storefront from "@/app/components/storefront";
import { getProductDetails, products } from "@/utils/catalog";

export function generateStaticParams() {
  return products.map(product => ({ sku: product.id }));
}

export default async function ProductPage({ params }: { params: Promise<{ sku: string }> }) {
  const { sku } = await params;
  const product = getProductDetails(sku);
  if (!product) notFound();
  return <Storefront product={product} />;
}
