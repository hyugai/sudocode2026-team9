import Storefront from "@/app/components/storefront";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Storefront view="tracking" orderId={id} />;
}
