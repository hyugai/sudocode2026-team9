"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";
import { productHref } from "@/utils/catalog";
import { money, payments, quote, regions, resolveItem, validateDelivery, type CartItem, type DemoOrder, type DemoScenario, type Delivery, type Quote, type ReceiptLine, type Region, type Payment } from "@/utils/commerce";
import { DemoNotice, PurchaseAction, QuantityControl } from "./purchase-controls";
import { usePurchase } from "./purchase-provider";

export type PurchaseView = "cart" | "checkout" | "review" | "success" | "orders" | "order" | "tracking";
const titles: Record<PurchaseView, string> = { cart: "Giỏ hàng", checkout: "Thanh toán", review: "Kiểm tra & xác nhận", success: "Đặt hàng demo thành công", orders: "Đơn hàng demo của bạn", order: "Chi tiết đơn hàng", tracking: "Theo dõi đơn hàng" };

export function PriceSummary({ calculated, children }: { calculated: Quote; children?: ReactNode }) {
  return <aside className="order-summary"><div className="commerce-panel"><h2>Tóm tắt đơn hàng</h2><dl className="commerce-values">
    <div><dt>Tạm tính</dt><dd>{money(calculated.subtotal)}</dd></div>
    <div><dt>Vận chuyển</dt><dd>{money(calculated.shipping)}</dd></div>
    <div><dt>Khuyến mãi giảm giá</dt><dd>{money(calculated.discount)}</dd></div>
    <div className="total"><dt>Tổng thanh toán · VND</dt><dd data-testid="order-total">{money(calculated.total)}</dd></div>
  </dl><p className="muted-note">Phí hiển thị đã gồm phụ thu nếu có.</p><details className="quote-explanation"><summary>Cách tính phí và giá</summary><p>{calculated.shippingReason}. Giá niêm yết BTC {calculated.referenceDate}, chưa phải báo giá trực tiếp. Ưu đãi cần xác minh chưa được áp dụng.</p></details></div>{children}</aside>;
}

function ReceiptLineView({ line, children }: { line: ReceiptLine; children?: ReactNode }) {
  return <article className="commerce-panel order-line" data-sku={line.sku}><h2><Link href={productHref(line.productSku)}>{line.name}</Link></h2><p className="muted-note">{line.sku}</p><dl className="commerce-values">
    <div><dt>Đơn giá niêm yết</dt><dd>{money(line.unitPrice)}</dd></div>
    <div><dt>Màu</dt><dd>{line.color}</dd></div><div><dt>Kích thước / phiên bản</dt><dd>{line.size}</dd></div>
    <div><dt>Số lượng</dt><dd>{line.quantity}</dd></div><div><dt>Thành tiền</dt><dd>{money(line.lineTotal)}</dd></div>
  </dl>{children}</article>;
}

function AddressSummary({ delivery }: { delivery: Delivery }) {
  return <section className="commerce-panel delivery-summary"><h2>Thông tin nhận hàng</h2><div><strong>{delivery.name} · {delivery.phone}</strong><p>{delivery.address}</p></div><dl className="commerce-values"><div><dt>Vận chuyển</dt><dd>{regions[delivery.region]?.label}<small>{regions[delivery.region]?.days} ngày làm việc tham khảo</small></dd></div><div><dt>Thanh toán</dt><dd>{payments[delivery.payment]}<small>Mô phỏng · chưa thu tiền</small></dd></div></dl></section>;
}

function SavedOrder({ order, success = false }: { order: DemoOrder; success?: boolean }) {
  return <><div className="commerce-panel success-banner">{success && <><h2>Đã lưu đơn hàng mô phỏng</h2><p className="success-message" role="status">Cảm ơn bạn! Bạn có thể xem lại chi tiết đơn demo bên dưới. Chưa có đơn hàng hoặc khoản thanh toán thực tế nào được tạo.</p></>}<p>Mã đơn demo: <strong>{order.id}</strong></p><p>Đã tiếp nhận (mô phỏng) · Chưa thanh toán</p></div><div className="commerce-columns"><div className="commerce-main">{order.quote.lines.map(line => <ReceiptLineView key={line.sku} line={line} />)}<AddressSummary delivery={order.delivery} /><p>Trạng thái: Đã tiếp nhận · mô phỏng</p><p>Thanh toán: Chưa thanh toán · mô phỏng</p></div><PriceSummary calculated={order.quote}><PurchaseAction href={success ? `/orders/${order.id}` : `/orders/${order.id}/tracking`}>{success ? "Xem đơn hàng" : "Theo dõi đơn hàng"}</PurchaseAction></PriceSummary></div></>;
}

export function PurchaseJourney({ view, orderId }: { view: PurchaseView; orderId?: string }) {
  const purchase = usePurchase();
  const router = useRouter();
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submissionLock = useRef(false);
  const items = view === "cart" || purchase.source === "cart" ? purchase.cart : purchase.buyNow;
  let calculated: Quote | null = null;
  let quoteError = "";
  if (items.length) { try { calculated = quote(items, purchase.delivery.region); } catch (e) { quoteError = e instanceof Error ? e.message : "Không tính được tổng tiền."; } }
  const order = purchase.orders.find(o => o.id === orderId);
  const action = (fn: () => void) => { setError(""); purchase.store.clearError(); try { fn(); } catch (e) { setError(e instanceof Error ? e.message : "Thao tác chưa hoàn tất. Hãy thử lại."); } };
  const next = () => {
    if (!calculated) { setError(quoteError || "Giỏ hàng đang trống."); return; }
    const errors = validateDelivery(purchase.delivery, calculated.total); setFieldErrors(errors);
    if (Object.keys(errors).length) { setError("Hãy sửa thông tin được đánh dấu trước khi tiếp tục."); requestAnimationFrame(() => document.querySelector<HTMLElement>("[aria-invalid=true]")?.focus()); return; }
    action(() => { purchase.store.review(); router.push("/checkout/review"); });
  };
  const submit = async () => {
    if (submissionLock.current) return;
    submissionLock.current = true;
    setError(""); setSubmitting(true);
    try { const result = await purchase.store.submit(confirmed); router.push(`/order-success/${result.id}`); }
    catch (e) { setError(e instanceof Error ? e.message : "Tạo đơn demo thất bại. Hãy thử lại thủ công."); }
    finally { setSubmitting(false); submissionLock.current = false; }
  };
  const busy = purchase.submitting || submitting;
  const changeDelivery = (nextDelivery: Delivery, field: string) => {
    setFieldErrors(previous => { const nextErrors = { ...previous }; delete nextErrors[field]; return nextErrors; });
    action(() => purchase.store.setDelivery(nextDelivery));
  };
  const deliveryField = (key: "name" | "phone" | "address", label: string, autoComplete: string) => <div className="checkout-field"><label htmlFor={`delivery-${key}`}>{label}</label><input id={`delivery-${key}`} name={key} type={key === "phone" ? "tel" : "text"} autoComplete={autoComplete} maxLength={key === "address" ? 500 : 100} required value={purchase.delivery[key]} aria-invalid={!!fieldErrors[key]} aria-describedby={fieldErrors[key] ? `error-${key}` : undefined} disabled={busy} onChange={e => changeDelivery({ ...purchase.delivery, [key]: e.target.value }, key)} />{fieldErrors[key] && <p id={`error-${key}`} className="error">{fieldErrors[key]}</p>}</div>;
  const cartLine = (item: CartItem) => {
    try {
      const l = resolveItem(item);
      const line: ReceiptLine = { sku: l.sku, productSku: l.product.sku, name: l.product.name, color: l.variant?.color ?? "Không áp dụng", size: String(l.variant?.size ?? "Không áp dụng"), unitPrice: l.unitPrice, quantity: l.quantity, lineTotal: l.lineTotal };
      return <ReceiptLineView key={item.sku} line={line}><QuantityControl label={`Số lượng ${l.product.name}`} quantity={item.quantity} max={l.stock} disabled={busy} onChange={qty => action(() => purchase.store.update(item.sku, qty))} /><button className="quiet-button remove-line" disabled={busy} onClick={() => action(() => purchase.store.remove(item.sku))}>Xóa sản phẩm</button></ReceiptLineView>;
    } catch (e) { return <article key={item.sku} className="commerce-panel"><p>{item.sku}</p><p className="error">{e instanceof Error ? e.message : "Sản phẩm không hợp lệ."}</p><button className="quiet-button remove-line" onClick={() => action(() => purchase.store.remove(item.sku))}>Xóa sản phẩm</button></article>; }
  };
  const empty = <div className="commerce-panel empty-cart"><h2>Giỏ hàng đang trống</h2><p>Chọn sản phẩm và phiên bản để bắt đầu đơn demo.</p><Link className="commerce-secondary" href="/#catalog">Khám phá sản phẩm</Link></div>;
  return <section className="purchase-page container" data-view={view} aria-labelledby="purchase-heading"><div className="purchase-heading"><h1 id="purchase-heading" tabIndex={-1}>{titles[view]}</h1><DemoNotice /></div>
    {(error || purchase.error) && <div role="alert" className="commerce-error"><p>{error || purchase.error}</p><button className="text-link" onClick={() => { setError(""); purchase.store.clearError(); }}>Đóng thông báo</button></div>}
    {!purchase.ready ? <p role="status" className="commerce-panel">Đang tải dữ liệu mua sắm…</p> : <>
      {view === "cart" && (!items.length ? empty : <div className="commerce-columns"><div className="commerce-main">{items.map(cartLine)}<p className="muted-note">Giỏ lưu trên trình duyệt này; chưa giữ hàng. Phí tạm tính theo khu vực đang chọn, có thể đổi tại thanh toán.</p></div>{calculated ? <PriceSummary calculated={calculated}><PurchaseAction onClick={() => action(() => { purchase.store.checkout("cart"); router.push("/checkout"); })}>Tiến hành thanh toán</PurchaseAction></PriceSummary> : <aside className="commerce-panel" role="alert"><p>{quoteError}</p><button className="text-link" onClick={() => action(() => { purchase.store.checkout("cart"); router.push("/checkout"); })}>Đổi khu vực vận chuyển</button></aside>}</div>)}
      {view === "checkout" && (!items.length ? empty : <form noValidate onSubmit={e => { e.preventDefault(); next(); }} className="commerce-columns checkout-form"><div className="commerce-main">
        {calculated?.lines.map(line => <ReceiptLineView key={line.sku} line={line} />)}
        {quoteError && <p role="alert" className="error">{quoteError} <Link className="text-link" href="/cart">Sửa giỏ</Link></p>}
        <div className="checkout-fields"><h2>Địa chỉ nhận hàng</h2>{deliveryField("name", "Tên người nhận", "name")}{deliveryField("phone", "Số điện thoại nhận hàng", "tel")}{deliveryField("address", "Số nhà, đường, phường/xã, quận/huyện, tỉnh/thành", "street-address")}<p className="muted-note">Địa chỉ chưa được xác minh tự động; chỉ lưu trong phiên demo của tab này, không cập nhật bộ nhớ Synee.</p></div>
        <fieldset className="commerce-options"><legend>Phương thức vận chuyển</legend>{(Object.entries(regions) as [Region, typeof regions[Region]][]).map(([key, value]) => <label key={key}><input type="radio" name="shipping-region" value={key} checked={purchase.delivery.region === key} disabled={busy} onChange={() => changeDelivery({ ...purchase.delivery, region: key }, "region")} /><span>{value.label}<small>{value.days} ngày làm việc tham khảo · VC-01</small></span></label>)}</fieldset>
        <p className="muted-note">Chọn khu vực đúng với địa chỉ. Thời gian không gồm ngày nghỉ; chưa có lịch giao cụ thể được xác minh.</p>
        <fieldset className="commerce-options" aria-describedby={fieldErrors.payment ? "error-payment" : undefined}><legend>Phương thức thanh toán</legend>{(Object.entries(payments) as [Payment, string][]).map(([key, label]) => <label key={key}><input type="radio" name="payment" value={key} checked={purchase.delivery.payment === key} disabled={busy} onChange={() => changeDelivery({ ...purchase.delivery, payment: key }, "payment")} /><span>{label} · demo</span></label>)}</fieldset>
        {fieldErrors.payment && <p id="error-payment" className="error" role="alert">{fieldErrors.payment}</p>}<p className="muted-note">COD chỉ cho tổng dưới 10 triệu. Chuyển khoản và ví chỉ mô phỏng lựa chọn; không nhập thông tin thẻ, không chuyển tiền.</p>
        <details className="demo-scenarios"><summary>Thử trạng thái mô phỏng</summary><label htmlFor="demo-scenario">Kịch bản demo khi xác nhận</label><select id="demo-scenario" value={purchase.scenario} disabled={busy} onChange={e => action(() => purchase.store.setScenario(e.target.value as DemoScenario))}><option value="success">Thành công (demo)</option><option value="order-failure">Lỗi tạo đơn (demo)</option><option value="payment-failure">Lỗi thanh toán online (demo)</option><option value="unavailable">Hết hàng khi xác nhận (demo)</option></select></details>
      </div>{calculated ? <PriceSummary calculated={calculated}><PurchaseAction type="submit" disabled={busy}>Kiểm tra đơn hàng</PurchaseAction></PriceSummary> : <div />}</form>)}
      {view === "review" && (purchase.review ? <><Link className="commerce-secondary review-back" href="/checkout" onClick={e => { if (busy) e.preventDefault(); }}>← Quay lại chỉnh sửa</Link><div className="commerce-columns"><div className="commerce-main">{purchase.review.quote.lines.map(line => <ReceiptLineView key={line.sku} line={line} />)}<AddressSummary delivery={purchase.review.delivery} /></div><PriceSummary calculated={purchase.review.quote}><p>Chỉ khi bấm xác nhận, bạn mới tạo đơn mẫu với tổng tiền đang hiển thị.</p><label className="confirmation"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />Tôi đã kiểm tra SKU, số lượng, địa chỉ, phí và phương thức thanh toán; đồng ý tạo đơn demo.</label><PurchaseAction disabled={!confirmed || busy} onClick={() => { void submit(); }}>{busy ? "Đang tạo đơn demo…" : "Xác nhận đặt hàng"}</PurchaseAction><p role="status">{busy ? "Đang lưu đơn demo, vui lòng chờ…" : "Bạn không cần thanh toán cho đơn mô phỏng này."}</p></PriceSummary></div></> : <div className="commerce-panel"><p>Chưa có thông tin xác nhận hợp lệ. Hãy kiểm tra lại đơn.</p><Link href="/checkout" className="commerce-secondary">Về thanh toán</Link></div>)}
      {view === "orders" && <div className="commerce-main"><p>Chỉ hiển thị đơn demo đã lưu trong tab này; không tra cứu đơn thật.</p>{purchase.orders.length ? purchase.orders.map(o => <div className="commerce-panel" key={o.id}><Link className="text-link" href={`/orders/${o.id}`}>{o.id}</Link><p>{money(o.quote.total)} · Đã tiếp nhận (mô phỏng) · chưa thanh toán</p></div>) : <p className="commerce-panel">Chưa có đơn hàng demo.</p>}</div>}
      {(view === "success" || view === "order") && (order ? <SavedOrder order={order} success={view === "success"} /> : <div className="commerce-panel"><h2>Không tìm thấy đơn demo trong phiên này</h2><p>Đơn không tồn tại trong tab hiện tại hoặc dữ liệu phiên đã bị xóa. Không có đơn thật để tra cứu từ trang này.</p><Link className="text-link" href="/orders">Xem đơn demo đã lưu</Link></div>)}
      {view === "tracking" && (order ? <><p>Mã đơn demo: <strong>{order.id}</strong></p><p>Trạng thái: Đã tiếp nhận · mô phỏng</p><ol className="tracking-stages">{["Đã tiếp nhận — trạng thái mẫu hiện tại", "Đang chuẩn bị — chưa diễn ra", "Đang giao — chưa diễn ra", "Đã nhận hàng — chưa diễn ra"].map((stage, index) => <li key={stage} aria-current={index === 0 ? "step" : undefined}>{String(index + 1).padStart(2, "0")} · {stage}</li>)}</ol><p className="muted-note">Dòng thời gian minh họa; chưa có sự kiện vận chuyển, mã vận đơn hoặc lịch giao được xác minh.</p><Link className="commerce-secondary" href={`/orders/${order.id}`}>Chi tiết đơn hàng</Link></> : <div className="commerce-panel"><p>Không tìm thấy đơn demo để theo dõi trong tab này.</p><Link href="/orders">Xem đơn demo</Link></div>)}
      {purchase.error && <button className="quiet-button" disabled={busy} onClick={() => action(() => purchase.store.reset())}>Xóa dữ liệu mua sắm demo để bắt đầu lại</button>}
      {(view === "cart" || view === "success") && <Link className="quiet-button continue-shopping" href="/#catalog">Tiếp tục mua sắm</Link>}
    </>}
  </section>;
}
