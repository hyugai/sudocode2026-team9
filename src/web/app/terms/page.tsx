import type { Metadata } from "next";
import Storefront from "../components/storefront";
import { informationPages } from "@/utils/information-pages";

export const metadata: Metadata = {
  title: "Điều khoản · Synee AI",
  description: informationPages[2].description,
};

export default function Page() {
  return <Storefront informationPage="terms" />;
}
