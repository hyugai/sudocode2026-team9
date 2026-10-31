import { catalogReferenceDate, getProductDetails, type ProductDetails } from "./demo-catalog.ts";
import inventory from "../data/inventory_timeline.json" with { type: "json" };
import promotions from "../data/promotions.json" with { type: "json" };

export type CartItem = { productSku: string; sku: string; quantity: number };
export type Payment = "COD" | "bank" | "momo" | "zalopay";
export type Region = "inner" | "outer" | "province" | "highland" | "remote";
export type DemoScenario = "success" | "order-failure" | "payment-failure" | "unavailable";
export type Delivery = { name: string; phone: string; address: string; region: Region; payment: Payment };
export const emptyDelivery: Delivery = { name: "", phone: "", address: "", region: "inner", payment: "COD" };
export const regions: Record<Region, { label: string; days: string; fee: number }> = {
  inner: { label: "Nội thành Hà Nội, TP.HCM, Đà Nẵng", days: "1–2", fee: 25000 },
  outer: { label: "Ngoại thành; Bình Dương, Đồng Nai, Hải Phòng, Cần Thơ", days: "2–3", fee: 35000 },
  province: { label: "Tỉnh thành khác", days: "2–4", fee: 35000 },
  highland: { label: "Tây Nguyên, Tây Bắc", days: "3–5", fee: 35000 },
  remote: { label: "Vùng sâu, hải đảo (không nhận hàng cồng kềnh)", days: "5–7", fee: 35000 },
};
export const payments: Record<Payment, string> = { COD: "COD khi nhận hàng", bank: "Chuyển khoản", momo: "Ví MoMo", zalopay: "Ví ZaloPay" };
export const money = (value: number) => `${new Intl.NumberFormat("vi-VN").format(value)}₫`;
export class CommerceError extends Error {}

export function stockFor(sku: string, fallback: number, on = catalogReferenceDate) {
  const events = inventory.events.filter(e => e.sku === sku && e.date <= on).sort((a, b) => a.date.localeCompare(b.date));
  return events.at(-1)?.qty ?? fallback;
}

export function selection(product: ProductDetails, sku: string) {
  const variant = product.variants.find(v => v.variant_sku === sku);
  if (product.variants.length ? !variant : sku !== product.sku) throw new CommerceError("Hãy chọn đúng màu và kích thước của sản phẩm.");
  const discontinued = "discontinued" in product.attributes && !!product.attributes.discontinued;
  const stock = discontinued ? 0 : stockFor(sku, variant?.stock ?? product.stock);
  const unitPrice = product.list_price_vnd + (variant?.price_delta_vnd ?? 0);
  return { product, variant, sku, stock, unitPrice, discontinued };
}

export function resolveItem(item: CartItem) {
  const product = getProductDetails(item.productSku);
  if (!product) throw new CommerceError(`Không tìm thấy sản phẩm ${item.productSku}. Hãy xóa dòng này.`);
  const resolved = selection(product, item.sku);
  if (!Number.isSafeInteger(item.quantity) || item.quantity < 1) throw new CommerceError("Số lượng phải là số nguyên từ 1 trở lên.");
  if (item.quantity > resolved.stock) throw new CommerceError(`${product.name}: chỉ còn ${resolved.stock} theo BTC ${catalogReferenceDate}.`);
  return { ...resolved, quantity: item.quantity, lineTotal: resolved.unitPrice * item.quantity };
}

export type ResolvedLine = ReturnType<typeof resolveItem>;
export type ReceiptLine = Pick<ResolvedLine, "sku" | "quantity" | "unitPrice" | "lineTotal"> & { productSku: string; name: string; color: string; size: string };
export type Quote = { lines: ReceiptLine[]; subtotal: number; shipping: number; baseShipping: number; surcharge: number; discount: number; total: number; shippingReason: string; region: Region; referenceDate: string };

/** Snapshot arithmetic only, never a live quote or inventory reservation. */
export function quote(items: CartItem[], region: Region): Quote {
  if (!items.length) throw new CommerceError("Giỏ hàng đang trống.");
  if (!Object.hasOwn(regions, region)) throw new CommerceError("Hãy chọn khu vực giao hàng hợp lệ.");
  if (items.length > 100 || new Set(items.map(i => i.sku)).size !== items.length) throw new CommerceError("Giỏ hàng không hợp lệ; hãy kiểm tra các dòng sản phẩm.");
  const resolved = items.map(resolveItem);
  const subtotal = resolved.reduce((sum, line) => sum + line.lineTotal, 0);
  const bulky = resolved.some(l => l.product.category === "gia-dung/may-loc-nuoc" || l.product.sku.startsWith("SKU-MB-STR") || l.product.sku === "SKU-MB-CAR");
  if (bulky && region === "remote") throw new CommerceError("VC-01: chưa hỗ trợ giao hàng cồng kềnh đến vùng sâu, hải đảo. Hãy chọn khu vực khác hoặc hỏi Synee.");
  const mom = promotions.promotions.find(p => p.promo_code === "MOM-FREESHIP");
  const motherOnly = resolved.every(l => l.product.category === "me-be");
  const motherFree = motherOnly && mom && mom.start <= catalogReferenceDate && mom.end >= catalogReferenceDate && subtotal >= (mom.min_order_vnd ?? Infinity);
  const baseShipping = subtotal >= 2000000 || motherFree ? 0 : regions[region].fee;
  const surcharge = bulky && region !== "inner" ? 30000 : 0;
  const shipping = baseShipping + surcharge;
  return {
    lines: resolved.map(l => ({ productSku: l.product.sku, sku: l.sku, name: l.product.name, color: l.variant?.color ?? "Không áp dụng", size: String(l.variant?.size ?? "Không áp dụng"), quantity: l.quantity, unitPrice: l.unitPrice, lineTotal: l.lineTotal })),
    subtotal, baseShipping, surcharge, shipping, discount: 0, total: subtotal + shipping, region, referenceDate: catalogReferenceDate,
    shippingReason: `${motherFree ? "MOM-FREESHIP" : subtotal >= 2000000 ? "VC-02: đơn từ 2 triệu miễn phí cơ bản" : "VC-02: phí cơ bản"}${surcharge ? " + phụ thu cồng kềnh 30.000₫" : ""}`,
  };
}

export function validateDelivery(delivery: Delivery, total: number): Record<string, string> {
  const errors: Record<string, string> = {};
  if (delivery.name.trim().length < 2 || delivery.name.length > 100) errors.name = "Nhập tên người nhận từ 2–100 ký tự.";
  if (!/^(?:0\d{9}|\+84\d{9})$/.test(delivery.phone.replace(/[\s.-]/g, ""))) errors.phone = "Nhập số điện thoại Việt Nam hợp lệ (10 số hoặc +84).";
  if (delivery.address.trim().length < 12 || delivery.address.length > 500) errors.address = "Nhập số nhà, đường, phường/xã, quận/huyện và tỉnh/thành (12–500 ký tự).";
  if (!Object.hasOwn(regions, delivery.region)) errors.region = "Chọn khu vực vận chuyển hợp lệ.";
  if (!Object.hasOwn(payments, delivery.payment)) errors.payment = "Chọn phương thức thanh toán hợp lệ.";
  // VC-03 says below 10M; the internal order tool uses >10M. Use the stricter public policy boundary.
  if (delivery.payment === "COD" && total >= 10000000) errors.payment = "VC-03: COD chỉ cho tổng dưới 10.000.000₫. Hãy chọn chuyển khoản hoặc ví (demo).";
  return errors;
}

export function parseCart(value: unknown): CartItem[] {
  if (!Array.isArray(value) || value.length > 100) throw new CommerceError("Dữ liệu giỏ hàng không hợp lệ.");
  return value.map(item => {
    if (!item || typeof item !== "object" || typeof item.productSku !== "string" || typeof item.sku !== "string" || !Number.isSafeInteger(item.quantity) || item.quantity < 1 || item.quantity > 10000) throw new CommerceError("Dữ liệu giỏ hàng không hợp lệ.");
    return { productSku: item.productSku, sku: item.sku, quantity: item.quantity };
  });
}

export type Review = { token: string; source: "cart" | "buy-now"; fingerprint: string; quote: Quote; delivery: Delivery; scenario: DemoScenario };
export type DemoOrder = { id: string; token: string; mode: "demo"; createdAt: string; status: "received"; paymentStatus: "unpaid"; quote: Quote; delivery: Delivery };
export function reviewFingerprint(items: CartItem[], delivery: Delivery, scenario: DemoScenario) {
  return JSON.stringify({ items, delivery, scenario, quote: quote(items, delivery.region) });
}

export interface StoragePort { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }
export const CART_KEY = "synee.demo.cart.v1";
export const SESSION_KEY = "synee.demo.purchase.v1";
export type PurchaseState = { ready: boolean; cart: CartItem[]; buyNow: CartItem[]; source: "cart" | "buy-now"; delivery: Delivery; scenario: DemoScenario; review: Review | null; orders: DemoOrder[]; submitting: boolean; error: string };
const initialState = (): PurchaseState => ({ ready: false, cart: [], buyNow: [], source: "cart", delivery: { ...emptyDelivery }, scenario: "success", review: null, orders: [], submitting: false, error: "" });

/** Persist only cart identities locally; addresses/receipts stay in this tab's session storage. */
export function createPurchaseStore(local: () => StoragePort, session: () => StoragePort, uuid = () => crypto.randomUUID(), delay = () => new Promise<void>(resolve => setTimeout(resolve, 350))) {
  let state = initialState();
  const listeners = new Set<() => void>();
  let pending: Promise<DemoOrder> | null = null;
  const emit = (patch: Partial<PurchaseState>) => { state = { ...state, ...patch }; listeners.forEach(fn => fn()); };
  const persistSession = (next: PurchaseState) => session().setItem(SESSION_KEY, JSON.stringify({ buyNow: next.buyNow, source: next.source, delivery: next.delivery, scenario: next.scenario, review: next.review, orders: next.orders }));
  const persist = (patch: Partial<PurchaseState>, cartChanged = false) => {
    const next = { ...state, ...patch, error: "" };
    try {
      persistSession(next);
      if (cartChanged) {
        try { local().setItem(CART_KEY, JSON.stringify(next.cart)); }
        catch (error) { persistSession(state); throw error; }
      }
      emit(next);
    } catch { emit({ error: "Không lưu được dữ liệu demo. Hãy cho phép lưu trữ trên trình duyệt rồi thử lại; giỏ và biểu mẫu được giữ." }); throw new CommerceError(state.error); }
  };
  const getItems = () => state.source === "buy-now" ? state.buyNow : state.cart;
  const ensureReady = () => { if (!state.ready || state.submitting) throw new CommerceError("Đang xử lý; vui lòng chờ."); };
  return {
    subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    getSnapshot: () => state,
    getServerSnapshot: () => serverState,
    hydrate() {
      if (state.ready) return;
      try {
        const cart = parseCart(JSON.parse(local().getItem(CART_KEY) || "[]"));
        const saved = JSON.parse(session().getItem(SESSION_KEY) || "null");
        if (saved && (typeof saved !== "object" || !Array.isArray(saved.orders) || saved.orders.some((o: DemoOrder) => !isDemoOrder(o)))) throw new CommerceError("Phiên mua sắm không hợp lệ.");
        emit({ ...initialState(), ready: true, cart, ...(saved ? { buyNow: parseCart(saved.buyNow), source: saved.source === "buy-now" ? "buy-now" : "cart", delivery: isDelivery(saved.delivery) ? saved.delivery : { ...emptyDelivery }, scenario: ["success", "order-failure", "payment-failure", "unavailable"].includes(saved.scenario) ? saved.scenario : "success", review: isReview(saved.review) ? saved.review : null, orders: saved.orders } : {}) });
      } catch { emit({ ready: true, error: "Không đọc được dữ liệu mua sắm đã lưu. Bạn có thể xóa dữ liệu demo để bắt đầu lại." }); }
    },
    clearError() { emit({ error: "" }); },
    reset() { ensureReady(); local().removeItem(CART_KEY); session().removeItem(SESSION_KEY); emit({ ...initialState(), ready: true }); },
    add(item: CartItem) {
      ensureReady(); resolveItem(item);
      const existing = state.cart.find(l => l.sku === item.sku);
      const nextItem = { ...item, quantity: item.quantity + (existing?.quantity ?? 0) };
      resolveItem(nextItem);
      persist({ cart: existing ? state.cart.map(l => l.sku === item.sku ? nextItem : l) : [...state.cart, item], review: null }, true);
    },
    update(sku: string, quantity: number) {
      ensureReady(); const line = state.cart.find(l => l.sku === sku); if (!line) return;
      resolveItem({ ...line, quantity });
      persist({ cart: state.cart.map(l => l.sku === sku ? { ...l, quantity } : l), review: null }, true);
    },
    remove(sku: string) { ensureReady(); persist({ cart: state.cart.filter(l => l.sku !== sku), review: null }, true); },
    checkout(source: "cart" | "buy-now", item?: CartItem) {
      ensureReady(); if (item) resolveItem(item);
      const items = source === "cart" ? state.cart : item ? [item] : state.buyNow;
      if (!items.length) throw new CommerceError("Giỏ hàng đang trống.");
      items.forEach(resolveItem);
      persist({ source, buyNow: source === "buy-now" ? items : state.buyNow, review: null });
    },
    setDelivery(delivery: Delivery) {
      ensureReady(); emit({ delivery, review: null, error: "" });
      try { persistSession(state); }
      catch { emit({ error: "Không lưu được biểu mẫu vào phiên; nội dung đang nhập vẫn được giữ. Cho phép lưu trữ rồi thử lại." }); }
    },
    setScenario(scenario: DemoScenario) { ensureReady(); persist({ scenario, review: null }); },
    review() {
      ensureReady();
      const items = getItems(); const calculated = quote(items, state.delivery.region);
      const errors = validateDelivery(state.delivery, calculated.total);
      if (Object.keys(errors).length) throw new CommerceError(Object.values(errors)[0]);
      const review: Review = { token: uuid(), source: state.source, fingerprint: reviewFingerprint(items, state.delivery, state.scenario), quote: calculated, delivery: { ...state.delivery }, scenario: state.scenario };
      persist({ review }); return review;
    },
    submit(confirmed: boolean): Promise<DemoOrder> {
      if (pending) return pending;
      const review = state.review;
      const replay = review && state.orders.find(o => o.token === review.token);
      if (replay) return Promise.resolve(replay);
      try {
        ensureReady();
        if (!confirmed || !review) throw new CommerceError("Hãy kiểm tra và xác nhận đơn trước khi tạo đơn demo.");
        if (review.fingerprint !== reviewFingerprint(getItems(), state.delivery, state.scenario)) throw new CommerceError("Thông tin đơn đã đổi; hãy kiểm tra lại trước khi xác nhận.");
        if (Object.keys(validateDelivery(state.delivery, review.quote.total)).length) throw new CommerceError("Thông tin giao hàng hoặc thanh toán không hợp lệ.");
      } catch (error) { return Promise.reject(error); }
      emit({ submitting: true, error: "" });
      pending = (async () => {
        try {
          await delay();
          if (review!.scenario === "unavailable") throw new CommerceError("Demo: sản phẩm vừa hết hàng. Đơn chưa được tạo; hãy sửa giỏ và kiểm tra lại.");
          if (review!.scenario === "payment-failure" && review!.delivery.payment !== "COD") throw new CommerceError("Demo: thanh toán thất bại. Chưa thu tiền hoặc tạo đơn; hãy đổi phương thức rồi xác nhận lại.");
          if (review!.scenario === "order-failure") throw new CommerceError("Demo: tạo đơn thất bại. Dữ liệu được giữ để bạn thử lại thủ công.");
          const order: DemoOrder = { id: `DEMO-${review!.token}`, token: review!.token, mode: "demo", createdAt: new Date().toISOString(), status: "received", paymentStatus: "unpaid", quote: structuredClone(review!.quote), delivery: { ...review!.delivery } };
          // Persist the receipt before altering the cart. A retry replays this token.
          const next = { ...state, orders: [order, ...state.orders] };
          persistSession(next);
          emit({ orders: next.orders });
          if (review!.source === "cart") {
            const cart = state.cart.filter(l => !review!.quote.lines.some(o => o.sku === l.sku));
            try { local().setItem(CART_KEY, JSON.stringify(cart)); emit({ cart }); }
            catch { emit({ error: "Đơn demo đã lưu; chưa xóa được giỏ. Kiểm tra đơn demo trước khi đặt lại." }); }
          } else emit({ buyNow: [] });
          return order;
        } catch (error) {
          const message = error instanceof CommerceError ? error.message : "Không lưu được đơn demo. Chưa tạo đơn hoặc thu tiền; hãy cho phép lưu trữ và thử lại.";
          emit({ error: message }); throw new CommerceError(message);
        } finally { emit({ submitting: false }); pending = null; }
      })();
      return pending;
    },
  };
}
const serverState = initialState();
function isReview(value: unknown): value is Review {
  if (!value || typeof value !== "object") return false;
  const r = value as Review;
  return typeof r.token === "string" && /^[a-zA-Z0-9-]+$/.test(r.token) && typeof r.fingerprint === "string" && isQuote(r.quote) && isDelivery(r.delivery);
}
function isDemoOrder(value: unknown): value is DemoOrder {
  if (!value || typeof value !== "object") return false;
  const o = value as DemoOrder;
  return typeof o.id === "string" && /^DEMO-[a-zA-Z0-9-]+$/.test(o.id) && typeof o.token === "string" && o.id === `DEMO-${o.token}` && o.mode === "demo" && o.status === "received" && o.paymentStatus === "unpaid" && isQuote(o.quote) && isDelivery(o.delivery);
}
function isDelivery(value: unknown): value is Delivery {
  if (!value || typeof value !== "object") return false;
  const d = value as Delivery;
  return typeof d.name === "string" && typeof d.phone === "string" && typeof d.address === "string" && Object.hasOwn(regions, d.region) && Object.hasOwn(payments, d.payment);
}
function isQuote(value: unknown): value is Quote {
  if (!value || typeof value !== "object") return false;
  const q = value as Quote;
  return Array.isArray(q.lines) && q.lines.length > 0 && q.lines.length <= 100 && q.lines.every(l => l && [l.sku, l.productSku, l.name, l.color, l.size].every(v => typeof v === "string") && Number.isSafeInteger(l.quantity) && l.quantity > 0 && Number.isSafeInteger(l.unitPrice) && l.unitPrice >= 0 && l.lineTotal === l.unitPrice * l.quantity)
    && [q.subtotal, q.shipping, q.baseShipping, q.surcharge, q.discount, q.total].every(n => Number.isSafeInteger(n) && n >= 0)
    && q.subtotal === q.lines.reduce((n, l) => n + l.lineTotal, 0) && q.shipping === q.baseShipping + q.surcharge && q.total === q.subtotal - q.discount + q.shipping && Object.hasOwn(regions, q.region) && typeof q.shippingReason === "string" && typeof q.referenceDate === "string";
}
