import type { Metadata } from "next";
import { AuthScreen } from "../auth-screen";

export const metadata: Metadata = {
  title: "Đăng ký · Synee AI",
  description: "Tạo tài khoản Synee AI và SUDO market bằng email.",
};

export default function Page() {
  return <AuthScreen key="register" mode="register" />;
}
