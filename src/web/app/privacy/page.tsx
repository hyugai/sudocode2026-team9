import type { Metadata } from "next";
import Storefront from "../components/storefront";
import { informationPages } from "@/utils/information-pages";

export const metadata: Metadata = {
  title: "Chính sách bảo mật · Synee AI",
  description: informationPages[1].description,
};

export default function Page() {
  return <Storefront informationPage="privacy" />;
}
