import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { money, selection, type CartItem } from "@/utils/commerce";
import { usePurchase } from "./purchase-provider";
import { DemoNotice, PurchaseAction, QuantityControl } from "./purchase-controls";
import type { Consultation } from "@/utils/use-conversation";
import { applianceSubcategories, catalogReferenceDate, categoryFor, type ProductDetails } from "@/utils/catalog";

const attributeLabels: Record<string, string> = {
  room_area_m2: "Diện tích phòng (m²)", features: "Tính năng", warranty_months: "Bảo hành (tháng)",
  child_safe_lock: "Khóa trẻ em", material: "Chất liệu", return_days: "Đổi trả (ngày)",
  max_weight_kg: "Trọng lượng tối đa (kg)", volume_ml: "Dung tích (ml)", stages: "Số lõi lọc",
  discontinued: "Ngừng kinh doanh", successor_sku: "SKU thay thế", bundle_of: "Sản phẩm trong bộ", saving_vnd: "Tiết kiệm (VND)",
};

export function ProductDetail({ product, onAsk, askDisabled }: {
  product: ProductDetails;
  onAsk: (context: Consultation) => void;
  askDisabled: boolean;
}) {
  const router = useRouter();
  const purchase = usePurchase();
  const [color, setColor] = useState("");
  const [size, setSize] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const variant = product.variants.find(v => v.color === color && String(v.size) === size);
  const sku = product.variants.length ? variant?.variant_sku : product.sku;
  const selected = sku ? selection(product, sku) : null;
  const validQuantity = Number.isSafeInteger(quantity) && quantity > 0 && quantity <= (selected?.stock ?? 0);
  const item: CartItem = { productSku: product.sku, sku: sku ?? "", quantity };
  const choose = (field: "color" | "size", value: string) => { if (field === "color") setColor(value); else setSize(value); setQuantity(1); setError(""); setFeedback(""); };
  const buy = (direct: boolean) => {
    setError(""); setFeedback("");
    try {
      if (direct) { purchase.store.checkout("buy-now", item); router.push("/checkout"); }
      else { purchase.store.add(item); setFeedback("Đã thêm vào giỏ hàng demo."); }
    } catch (e) { setError(e instanceof Error ? e.message : "Không cập nhật được giỏ hàng; hãy thử lại."); }
  };
  const category = categoryFor(product.category);
  const subcategory = applianceSubcategories.find(c => c.sourceCategory === product.category)?.name;
  const price = money(selected?.unitPrice ?? product.list_price_vnd);
  const attributes = Object.entries(product.attributes);
  return <section className="product-detail container" data-sku={product.sku} aria-labelledby="product-title">
    <nav className="pdp-breadcrumb" aria-label="Đường dẫn sản phẩm"><Link className="pdp-back" href="/#catalog">Trang chủ</Link><span> / {category}{subcategory ? ` / ${subcategory}` : ""} / {product.sku}</span></nav>
    <DemoNotice />
    <div className="pdp-overview">
      <div className="pdp-gallery"><div className="missing-photo pdp-photo"><div><p>Ảnh sản phẩm</p><p>Chưa có ảnh từ BTC</p></div></div><div className="gallery-note"><span className="gallery-placeholder" aria-hidden="true" /><p>Chưa có ảnh từ catalog BTC; không có ảnh khác để chuyển.</p></div></div>
      <div className="pdp-info">
        <p className="pdp-sku">{product.sku} · BTC {catalogReferenceDate}</p>
        <h1 id="product-title">{product.name}</h1>
        <p className="muted-note">Chưa có đánh giá / lượt bán</p>
        <p className="price">{price}</p>
        <p className="muted-note">{selected ? `Tồn ${selected.stock} · BTC ${catalogReferenceDate}${selected.discontinued ? " · Ngừng kinh doanh" : ""}` : "Chọn màu và kích thước để xem đúng giá, SKU và tồn kho."}</p>
        {product.variants.length > 0 && <>
          <fieldset className="variant-options"><legend>Màu / kiểu dáng</legend>{[...new Set(product.variants.map(v => v.color))].map(value => <button type="button" key={value} aria-pressed={color === value} onClick={() => choose("color", value)}>{({ den: "Đen", trang: "Trắng", xam: "Xám", navy: "Navy", be: "Be" } as Record<string, string>)[value] ?? value}</button>)}</fieldset>
          <fieldset className="variant-options"><legend>Kích thước / phiên bản</legend>{[...new Set(product.variants.map(v => String(v.size)))].map(value => <button type="button" key={value} aria-pressed={size === value} onClick={() => choose("size", value)}>{value}</button>)}</fieldset>
          <p className="selected-sku" role="status">{sku ? `SKU đã chọn: ${sku}` : color && size ? "Phiên bản này không có trong catalog." : "Chưa chọn đủ màu và kích thước."}</p>
        </>}
        <QuantityControl quantity={quantity} max={selected?.stock ?? 0} onChange={setQuantity} disabled={!selected || !selected.stock || purchase.submitting} />
        <p className="muted-note" id="purchase-availability">{!purchase.ready ? "Đang tải giỏ hàng…" : !sku ? "Chọn phiên bản trước khi mua." : !selected?.stock ? "Sản phẩm tạm hết hàng hoặc ngừng kinh doanh trong dữ liệu BTC." : !validQuantity ? `Số lượng phải là số nguyên từ 1 đến ${selected.stock}.` : `Tạm tính: ${money((selected?.unitPrice ?? 0) * quantity)} · chưa gồm vận chuyển.`}</p>
        <div className="pdp-purchase-actions"><button type="button" className="commerce-secondary" disabled={!purchase.ready || !validQuantity || purchase.submitting} aria-describedby="purchase-availability" onClick={() => buy(false)}>Thêm vào giỏ</button><PurchaseAction disabled={!purchase.ready || !validQuantity || purchase.submitting} onClick={() => buy(true)}>Mua ngay</PurchaseAction></div>
        {feedback && <p role="status">{feedback} <Link href="/cart" className="text-link">Xem giỏ hàng</Link></p>}
        {error && <p role="alert" className="error">{error}</p>}
        <button className="pdp-ask press-button" onClick={() => onAsk({ sku: sku ?? product.sku, name: product.name, price, quantity })} disabled={askDisabled} aria-describedby="pdp-ask-note"><span className="button-rear" aria-hidden="true" /><span className="button-face">Hỏi Synee AI</span></button>
        <p id="pdp-ask-note" className="muted-note">{askDisabled ? "Chờ phản hồi hoặc bỏ ghi âm để hỏi về sản phẩm." : "Mở trò chuyện với thông tin sản phẩm; bạn xem lại trước khi gửi."}</p>
        <p className="muted-note">Mua ngay chỉ mở bước thanh toán demo; đơn chỉ tạo sau khi bạn xác nhận.</p>
      </div>
    </div>
    <div className="pdp-details">
      <div><h2>Mô tả sản phẩm</h2><p>Thương hiệu: {product.brand} · Danh mục: {product.category}.</p></div>
      {attributes.length > 0 && <div><h2>Thông số kỹ thuật</h2><dl>{attributes.map(([key, value]) => <div key={key}><dt>{attributeLabels[key] || key}</dt><dd>{typeof value === "boolean" ? value ? "Có" : "Không" : Array.isArray(value) ? value.join(", ") : String(value)}</dd></div>)}</dl></div>}
    </div>
  </section>;
}
