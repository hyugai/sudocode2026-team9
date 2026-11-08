import type { Metadata } from "next";
import { AuthScreen } from "../auth-screen";

export const metadata: Metadata = {
  title: "Đăng ký · Synee AI",
  description: "Giao diện tạo tài khoản demo của Synee AI và SUDO market.",
};

export default function Page() {
  return <AuthScreen key="register" mode="register" />;
}
