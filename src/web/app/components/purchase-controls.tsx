import type { ReactNode } from "react";
import Link from "next/link";

export function PurchaseAction({ children, href, onClick, disabled = false, type = "button", className = "" }: { children: ReactNode; href?: string; onClick?: () => void; disabled?: boolean; type?: "button" | "submit"; className?: string }) {
  const content = <><span className="button-rear" aria-hidden="true" /><span className="button-face">{children}</span></>;
  return href && !disabled ? <Link className={`press-button purchase-action ${className}`} href={href}>{content}</Link> : <button type={type} className={`press-button purchase-action ${className}`} disabled={disabled} onClick={onClick}>{content}</button>;
}
export function QuantityControl({ quantity, max, onChange, disabled, label = "Số lượng" }: { quantity: number; max: number; onChange: (value: number) => void; disabled?: boolean; label?: string }) {
  return <div className="quantity-control" role="group" aria-label={label}>
    <button type="button" aria-label={`Giảm ${label.toLocaleLowerCase("vi")}`} disabled={disabled || quantity <= 1} onClick={() => onChange(quantity - 1)}>−</button>
    <input type="number" inputMode="numeric" min={1} max={Math.max(1, max)} step={1} aria-label={label} value={quantity || ""} disabled={disabled} onChange={e => onChange(Number(e.target.value))} />
    <button type="button" aria-label={`Tăng ${label.toLocaleLowerCase("vi")}`} disabled={disabled || quantity >= max} onClick={() => onChange(quantity + 1)}>+</button>
  </div>;
}
export function DemoNotice() {
  return <p className="demo-notice">Mua sắm mô phỏng · Giá và tồn theo BTC 15/10/2026. Không tạo đơn thật, giữ hàng hoặc thu tiền. Khuyến mãi giảm giá chưa được xác minh và chưa áp dụng.</p>;
}
