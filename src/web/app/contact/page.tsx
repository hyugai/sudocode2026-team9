import type { Metadata } from "next";
import Storefront from "../components/storefront";
import { informationPages } from "@/utils/information-pages";

export const metadata: Metadata = {
  title: "Liên hệ · Synee AI",
  description: informationPages[3].description,
};

export default function Page() {
  return <Storefront informationPage="contact" />;
}
