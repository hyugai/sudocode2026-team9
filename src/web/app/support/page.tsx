import type { Metadata } from "next";
import Storefront from "../components/storefront";
import { informationPages } from "@/utils/information-pages";

export const metadata: Metadata = {
  title: "Hỗ trợ · Synee AI",
  description: informationPages[0].description,
};

export default function Page() {
  return <Storefront informationPage="support" />;
}
