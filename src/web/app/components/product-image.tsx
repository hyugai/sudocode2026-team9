"use client";

import Image from "next/image";
import { useState } from "react";
import { productIllustrationFor } from "@/utils/product-illustrations";

export function ProductImage({ sku, name, detail = false }: { sku: string; name: string; detail?: boolean }) {
  const src = productIllustrationFor(sku);
  const [failedSrc, setFailedSrc] = useState<string>();
  const available = !!src && failedSrc !== src;

  return <div className={`${detail ? "pdp-photo" : "product-photo"} ${available ? "product-illustration" : "missing-photo"}`}>
    {available ? <>
      <Image src={src} alt={`Ảnh minh họa ${name}`} fill
        sizes={detail ? "(max-width: 760px) calc(100vw - 32px), (max-width: 1279px) 50vw, 640px" : "(max-width: 760px) 50vw, (max-width: 1100px) 33vw, 240px"}
        loading={detail ? "eager" : "lazy"} onError={() => setFailedSrc(src)} />
      <span className="product-image-label">Ảnh minh họa</span>
    </> : <div><p>Chưa có ảnh minh họa</p><p>{sku}</p></div>}
  </div>;
}
