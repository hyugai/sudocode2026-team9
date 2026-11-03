import Link from "next/link";
import { useState } from "react";
import { QuantityControl } from "./purchase-controls";
import { ProductImage } from "./product-image";
import type { Consultation } from "@/utils/use-conversation";
import { applianceSubcategories, categoryFor, formatMoney, type LiveProductDetails } from "@/utils/catalog";

const attributeLabels: Record<string, string> = {
  room_area_m2: "Diện tích phòng (m²)", features: "Tính năng", warranty_months: "Bảo hành (tháng)",
  child_safe_lock: "Khóa trẻ em", material: "Chất liệu", return_days: "Đổi trả (ngày)",
  max_weight_kg: "Trọng lượng tối đa (kg)", volume_ml: "Dung tích (ml)", stages: "Số lõi lọc",
  discontinued: "Ngừng kinh doanh", successor_sku: "SKU thay thế", bundle_of: "Sản phẩm trong bộ", saving_vnd: "Tiết kiệm (VND)",
};

export function ProductDetail({ product, onAsk, askDisabled }: {
  product: LiveProductDetails;
  onAsk: (context: Consultation) => void;
  askDisabled: boolean;
}) {
  const [color, setColor] = useState("");
  const [size, setSize] = useState("");
  const [quantity, setQuantity] = useState(1);
  const variant = product.variants.find(v => v.color === color && String(v.size) === size);
  const sku = product.variants.length ? variant?.variant_sku : product.sku;
  const selected = sku ? {
    stock: product.attributes.discontinued ? 0 : variant ? variant.stock : product.stock,
    unitPrice: product.list_price_vnd + (variant?.price_delta_vnd ?? 0),
    discontinued: product.attributes.discontinued === true,
  } : null;
  const validQuantity = Number.isSafeInteger(quantity) && quantity > 0 && quantity <= (selected?.stock ?? 0);
  const choose = (field: "color" | "size", value: string) => { if (field === "color") setColor(value); else setSize(value); setQuantity(1); };
  const category = categoryFor(product.category);
  const subcategory = applianceSubcategories.find(c => c.sourceCategory === product.category)?.name;
  const price = formatMoney(selected?.unitPrice ?? product.list_price_vnd);
  const attributes = Object.entries(product.attributes);
  return <section className="product-detail container" data-sku={product.sku} aria-labelledby="product-title">
    <nav className="pdp-breadcrumb" aria-label="Đường dẫn sản phẩm"><Link className="pdp-back" href="/#catalog">Trang chủ</Link><span> / {category}{subcategory ? ` / ${subcategory}` : ""} / {product.sku}</span></nav>
    <div className="pdp-overview">
      <div className="pdp-gallery"><ProductImage sku={product.sku} name={product.name} detail /><p className="gallery-note">Ảnh minh họa cho bản demo; kiểu dáng thực tế có thể khác.</p></div>
      <div className="pdp-info">
        <p className="pdp-sku">{product.sku} · Catalog Neon</p>
        <h1 id="product-title">{product.name}</h1>
        <p className="muted-note">Chưa có đánh giá / lượt bán</p>
        <p className="price">{price}</p>
        <p className="muted-note">{selected ? `Tồn ${selected.stock} theo database${selected.discontinued ? " · Ngừng kinh doanh" : ""}` : "Chọn màu và kích thước để xem đúng giá, SKU và tồn kho."}</p>
        {product.variants.length > 0 && <>
          <fieldset className="variant-options"><legend>Màu / kiểu dáng</legend>{[...new Set(product.variants.map(v => v.color))].map(value => <button type="button" key={value} aria-pressed={color === value} onClick={() => choose("color", value)}>{({ den: "Đen", trang: "Trắng", xam: "Xám", navy: "Navy", be: "Be" } as Record<string, string>)[value] ?? value}</button>)}</fieldset>
          <fieldset className="variant-options"><legend>Kích thước / phiên bản</legend>{[...new Set(product.variants.map(v => String(v.size)))].map(value => <button type="button" key={value} aria-pressed={size === value} onClick={() => choose("size", value)}>{value}</button>)}</fieldset>
          <p className="selected-sku" role="status">{sku ? `SKU đã chọn: ${sku}` : color && size ? "Phiên bản này không có trong catalog." : "Chưa chọn đủ màu và kích thước."}</p>
        </>}
        <QuantityControl quantity={quantity} max={selected?.stock ?? 0} onChange={setQuantity} disabled={!selected || !selected.stock} />
        <p className="muted-note" id="purchase-availability">{!sku ? "Chọn phiên bản để xem giá và tồn kho." : !selected?.stock ? "Sản phẩm tạm hết hàng hoặc ngừng kinh doanh." : !validQuantity ? `Số lượng phải là số nguyên từ 1 đến ${selected.stock}.` : `Tạm tính: ${formatMoney((selected?.unitPrice ?? 0) * quantity)} · chưa gồm vận chuyển.`}</p>
        <p className="muted-note">Giỏ hàng và thanh toán demo chưa kết nối với catalog Neon. Hãy hỏi Synee AI nếu bạn muốn được tư vấn sản phẩm này.</p>
        <button className="pdp-ask commerce-secondary" onClick={() => onAsk({ sku: sku ?? product.sku, name: product.name, price, quantity })} disabled={askDisabled} aria-controls="floating-chat" aria-describedby="pdp-ask-note">Hỏi Synee AI</button>
        <p id="pdp-ask-note" className="muted-note">{askDisabled ? "Chờ phản hồi hoặc bỏ ghi âm để hỏi về sản phẩm." : "Mở trò chuyện với thông tin sản phẩm; bạn xem lại trước khi gửi."}</p>
      </div>
    </div>
    <div className="pdp-details">
      <div><h2>Mô tả sản phẩm</h2><p>Thương hiệu: {product.brand} · Danh mục: {product.category}.</p></div>
      {attributes.length > 0 && <div><h2>Thông số kỹ thuật</h2><dl>{attributes.map(([key, value]) => <div key={key}><dt>{attributeLabels[key] || key}</dt><dd>{typeof value === "boolean" ? value ? "Có" : "Không" : Array.isArray(value) ? value.join(", ") : String(value)}</dd></div>)}</dl></div>}
    </div>
  </section>;
}
