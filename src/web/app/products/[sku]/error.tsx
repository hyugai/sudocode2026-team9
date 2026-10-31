"use client";

import Link from "next/link";

export default function ProductError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="container empty-catalog" role="alert">
    <h1>Chưa tải được sản phẩm từ backend</h1>
    <p>Vui lòng thử lại sau khi dịch vụ sẵn sàng.</p>
    <button type="button" className="commerce-secondary" onClick={reset}>Thử lại</button>
    <Link className="text-link" href="/">Về trang chủ</Link>
  </main>;
}
