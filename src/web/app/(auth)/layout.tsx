import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import "./auth.css";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return <div className="auth-site">
    <a className="skip-link" href="#auth-main">Đến biểu mẫu</a>
    <header className="auth-header container">
      <Link href="/" className="auth-wordmark" aria-label="SUDO CODE — Trang chủ"><Image src="/figma/a-imgSudoCodeOfficialVectorWordmark.svg" width={136} height={20} alt="SUDO CODE" unoptimized /></Link>
      <nav aria-label="Điều hướng tài khoản"><Link href="/support">Hỗ trợ</Link><Link href="/" className="auth-back"><span aria-hidden="true">←</span> Trang chủ</Link></nav>
    </header>
    <main id="auth-main" className="auth-main container">{children}</main>
    <footer className="auth-footer container"><p>© SUDO market · Có Synee đồng hành</p><nav aria-label="Thông tin và chính sách"><Link href="/privacy">Chính sách bảo mật</Link><Link href="/terms">Điều khoản</Link><Link href="/contact">Liên hệ</Link></nav></footer>
  </div>;
}
