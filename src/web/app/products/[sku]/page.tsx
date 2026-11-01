import { notFound } from "next/navigation";
import Storefront from "@/app/components/storefront";
import { getLiveProduct } from "@/utils/live-catalog";

export default async function ProductPage({ params }: { params: Promise<{ sku: string }> }) {
  const { sku } = await params;
  const product = await getLiveProduct(sku);
  if (!product) notFound();
  return <Storefront product={product} />;
}
