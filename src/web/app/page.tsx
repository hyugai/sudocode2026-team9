import Storefront from "./components/storefront";

export default async function Page({ searchParams }: { searchParams: Promise<{ q?: string | string[]; category?: string | string[] }> }) {
  const { q, category } = await searchParams;
  return <Storefront key={`${q ?? ""}-${category ?? ""}`} initialSearch={typeof q === "string" ? q : ""} initialCategory={typeof category === "string" ? category : undefined} />;
}