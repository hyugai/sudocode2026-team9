import type { Metadata } from "next";
import { AuthScreen } from "../auth-screen";

export const metadata: Metadata = {
  title: "Đăng nhập · Synee AI",
  description: "Giao diện đăng nhập demo của Synee AI và SUDO market.",
};

export default function Page() {
  return <AuthScreen key="login" mode="login" />;
}
