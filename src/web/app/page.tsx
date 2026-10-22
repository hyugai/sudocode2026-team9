import Storefront from "./components/storefront";

export default async function Page({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  const { q } = await searchParams;
  return <Storefront initialSearch={typeof q === "string" ? q : ""} />;
}
