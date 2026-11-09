"use client";

import Link from "next/link";
import { usePurchase } from "./purchase-provider";

export function CartLink({ compact = false }: { compact?: boolean }) {
  const { cart, ready } = usePurchase();
  const quantity = cart.reduce((total, item) => total + item.quantity, 0);
  const label = ready ? `Giỏ hàng, ${quantity} sản phẩm` : "Giỏ hàng, đang khôi phục";
  const badge = <span className="cart-count" aria-hidden="true">{quantity}</span>;

  return <Link href="/cart" className={`cart-link${compact ? " ai-icon-button ai-cart-link" : ""}`} aria-label={label} title={label}>
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.41667" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1.66667 2.5H4.16667L6.66667 13.3333H15.8333L18.3333 5H5M7.5 17.5H7.50833M15 17.5H15.0083" />
    </svg>
    {compact ? badge : <span>Giỏ hàng {badge}</span>}
    <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">{ready ? `Giỏ hàng có ${quantity} sản phẩm.` : "Đang khôi phục giỏ hàng."}</span>
  </Link>;
}
