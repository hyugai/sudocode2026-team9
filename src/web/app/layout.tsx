import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { ConversationProvider } from "./components/conversation-provider";
import { PurchaseProvider } from "./components/purchase-provider";

const inter = localFont({
  variable: "--font-inter",
  display: "swap",
  src: [
    { path: "../public/fonts/inter-400.ttf", weight: "400", style: "normal" },
    { path: "../public/fonts/inter-500.ttf", weight: "500", style: "normal" },
    { path: "../public/fonts/inter-600.ttf", weight: "600", style: "normal" },
    { path: "../public/fonts/inter-700.ttf", weight: "700", style: "normal" },
  ],
});

export const metadata: Metadata = {
  title: "Synee AI · SUDO CODE",
  description: "Synee nhớ điều bạn cần, đồng hành đến khi nhận. Tư vấn tận tâm, giao hàng tận tay.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="vi"
      className={`${inter.variable} h-full antialiased`}
    >
      <body><ConversationProvider><PurchaseProvider>{children}</PurchaseProvider></ConversationProvider></body>
    </html>
  );
}
