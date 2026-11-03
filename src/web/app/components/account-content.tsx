"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { useSharedConversation } from "./conversation-provider";
import { usePurchase } from "./purchase-provider";

export type AccountView = "profile" | "history";

export function AccountNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const authStatusId = useId();
  return <nav className="account-navigation" aria-label="Tài khoản khách">
    <Link href="/account" onClick={onNavigate}>Hồ sơ tư vấn</Link>
    <Link href="/orders" onClick={onNavigate}>Đơn hàng demo</Link>
    <Link href="/account/conversations" onClick={onNavigate}>Lịch sử hội thoại</Link>
    <div className="auth-unavailable"><p>Bạn đang dùng phiên khách. Đăng nhập, đăng ký và đăng xuất chưa được dịch vụ hỗ trợ.</p>
      <div><button type="button" disabled aria-describedby={authStatusId}>Đăng nhập</button><button type="button" disabled aria-describedby={authStatusId}>Đăng ký</button><button type="button" disabled aria-describedby={authStatusId}>Đăng xuất</button></div>
      <p id={authStatusId}>Chưa có tài khoản được xác thực. Số điện thoại tư vấn không phải thông tin đăng nhập.</p>
    </div>
  </nav>;
}

export function GuestProfile({ idPrefix = "customer" }: { idPrefix?: string }) {
  const c = useSharedConversation();
  const purchase = usePurchase();
  const [phone, setPhone] = useState(c.customerPhone);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [allowReset, setAllowReset] = useState(false);
  const changing = phone.trim() !== c.customerPhone;
  const needsReset = changing && (!!c.sessionId || purchase.cart.length > 0 || purchase.orders.length > 0 || !!purchase.delivery.name || !!purchase.buyNow.length);
  return <form className="account-form" noValidate onSubmit={e => {
    e.preventDefault(); setSaved(false);
    if (phone.trim() && !/^(?:0\d{9}|\+84\d{9})$/.test(phone.trim())) { setError("Nhập số điện thoại Việt Nam gồm 10 số hoặc +84."); return; }
    if (needsReset && !allowReset) { setError("Xác nhận bắt đầu phiên khách mới trước khi đổi số."); return; }
    try {
      if (changing) purchase.store.reset();
      c.setCustomerPhone(phone); setError(""); setSaved(true); setAllowReset(false);
    } catch { setError("Chưa xóa được dữ liệu mua sắm cũ. Hãy thử lại trước khi đổi số."); }
  }}>
    <h2>Hồ sơ tư vấn · khách</h2><p>Chỉ dùng số điện thoại bạn cung cấp để hỗ trợ tư vấn. Đây không phải tài khoản hay hồ sơ khách hàng đã xác thực.</p>
    <label htmlFor={`${idPrefix}-phone`}>Số điện thoại tư vấn (không bắt buộc)</label><input id={`${idPrefix}-phone`} type="tel" autoComplete="tel" maxLength={30} placeholder="VD: 0901234567" value={phone} onChange={e => { setPhone(e.target.value); setSaved(false); }} disabled={c.isLoading || !c.sessionReady} aria-invalid={!!error} aria-describedby={`${idPrefix}-note`} />
    <p id={`${idPrefix}-note`} className="muted-note">Đổi số sẽ bắt đầu hội thoại mới để tránh lẫn nội dung của hai người. Dữ liệu đơn demo không được xác minh theo số điện thoại.</p>
    {needsReset && <label className="confirmation"><input className="confirm-profile-reset" type="checkbox" checked={allowReset} onChange={e => setAllowReset(e.target.checked)} disabled={c.isLoading} />Tôi đồng ý xóa hội thoại, bản nháp, giỏ và đơn demo trên thiết bị trước khi đổi số tư vấn.</label>}
    {error && <p className="error" role="alert">{error}</p>}
    <button className="commerce-secondary save-profile" disabled={c.isLoading || !c.sessionReady || !purchase.ready} type="submit">Lưu thông tin tư vấn</button>
    {saved && <p role="status">Đã lưu cho phiên khách trong tab này.</p>}
    <p className="session-id muted-note">Hội thoại: {c.sessionId || "Chưa bắt đầu"}</p>
    <p className="muted-note">Hội thoại và bản nháp lưu trong tab này để khôi phục khi tải lại. File ghi âm chỉ được giữ khi tab đang mở. Tránh dùng chung thiết bị cho nội dung riêng tư.</p>
    {c.sessionNotice && <p role="status">{c.sessionNotice}</p>}
  </form>;
}

function ConversationHistory() {
  const c = useSharedConversation();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);
  const lock = useRef(false);
  return <div className="account-history"><h2>Hội thoại trong tab này</h2>
    <p>Đây là bản lưu của phiên khách, không phải lịch sử tài khoản. Chưa thể tra cứu hội thoại từ thiết bị khác.</p>
    {!c.sessionReady ? <p role="status">Đang khôi phục hội thoại…</p> : <>
      <div className="account-transcript" role="log" aria-label="Hội thoại đã lưu">{c.messages.map((m, i) => <article key={i}><strong>{m.role === "agent" ? "Synee AI" : "Bạn"}</strong><p>{m.text}</p></article>)}</div>
      <Link href="/ai-chat" className="commerce-secondary">Tiếp tục trò chuyện</Link>
      {c.sessionId && <div className="end-conversation"><h3>Kết thúc hội thoại hiện tại</h3><p>Synee sẽ bắt đầu một hội thoại mới. Thao tác này không xóa hồ sơ hoặc bộ nhớ đã lưu tại dịch vụ.</p>
        <label className="confirmation"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} disabled={c.isLoading} />Tôi đồng ý kết thúc và xóa bản hội thoại hiện tại khỏi tab này.</label>
        <button className="commerce-secondary end-session" disabled={!confirm || c.isLoading} onClick={async () => {
          if (lock.current) return; lock.current = true; setError("");
          try { await c.endConversation(); setComplete(true); setConfirm(false); }
          catch (e) { setError(e instanceof Error ? e.message : "Chưa kết thúc được hội thoại."); }
          finally { lock.current = false; }
        }}>{c.isLoading ? "Đang kết thúc…" : "Kết thúc hội thoại"}</button>
      </div>}
      {error && <p role="alert" className="error">{error}</p>}{complete && <p role="status">Đã kết thúc hội thoại. Bạn có thể bắt đầu một cuộc tư vấn mới.</p>}
    </>}
    {c.debugLogs.length > 0 && <details className="debug-logs"><summary>Thông tin chẩn đoán hội thoại</summary>{c.debugLogs.map((log, i) => <article key={i}><p>{log.userMessage}</p><pre>{JSON.stringify(log.debug, null, 2)}</pre></article>)}</details>}
  </div>;
}

export function AccountPage({ view }: { view: AccountView }) {
  const c = useSharedConversation();
  return <section className="account-page container" aria-labelledby="account-heading"><h1 id="account-heading">{view === "profile" ? "Thông tin tư vấn" : "Lịch sử hội thoại"}</h1><div className="account-columns"><aside className="commerce-panel"><AccountNavigation /></aside><div className="commerce-panel">{!c.sessionReady ? <p role="status">Đang khôi phục thông tin tư vấn…</p> : view === "profile" ? <GuestProfile key={c.customerPhone} idPrefix="profile" /> : <ConversationHistory />}</div></div></section>;
}
