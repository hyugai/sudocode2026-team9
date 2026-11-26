"use client";

import Link from "next/link";
import { useMemo } from "react";
import { formatMoney, productHref, type LiveProductDetails } from "@/utils/catalog";
import { matchChatProducts } from "@/utils/chat-products";
import { ProductImage } from "./product-image";

export function ChatProductCards({ text, catalog }: { text: string; catalog: readonly LiveProductDetails[] }) {
  const products = useMemo(() => matchChatProducts(text, catalog), [text, catalog]);
  if (!products.length) return null;
  return <ul className="chat-product-cards" aria-label="Sản phẩm được nhắc đến">
    {products.map(product => <li key={product.sku}>
      <Link className="chat-product-card" href={productHref(product.productSku)}>
        <div className="chat-product-image"><ProductImage sku={product.productSku} name={product.name} /></div>
        <div className="chat-product-info">
          <strong>{product.name}</strong>
          <span className="chat-product-sku">{product.sku}{product.variantLabel ? ` · ${product.variantLabel}` : ""}</span>
          <span className="chat-product-price">{product.fromPrice ? "Từ " : ""}{formatMoney(product.price)}</span>
          <small>Giá niêm yết{product.unavailable ? " · Tạm hết hàng hoặc ngừng bán" : ""}</small>
          <span className="chat-product-link">Xem sản phẩm →</span>
        </div>
      </Link>
    </li>)}
  </ul>;
}
