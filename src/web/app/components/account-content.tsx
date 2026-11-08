"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { useSharedConversation } from "./conversation-provider";
import { usePurchase } from "./purchase-provider";
import { useAuth } from "./auth-provider";

export type AccountView = "profile" | "history";

function AccountAuthLinks({ onNavigate }: { onNavigate?: () => void }) {
  const auth = useAuth();
  if (auth.user) return null;
  return <div className="account-auth-links" role="group" aria-label="Tài khoản"><Link href="/login" onClick={onNavigate}>Đăng nhập</Link><Link href="/register" onClick={onNavigate}>Đăng ký</Link></div>;
}

function AccountLogout({ onNavigate }: { onNavigate?: () => void }) {
  const auth = useAuth();
  const c = useSharedConversation();
  const purchase = usePurchase();
  const router = useRouter();
  const id = useId();
  const [error, setError] = useState("");
  return <div className="account-signout">
    <button type="button" className="account-logout" disabled={!auth.user || auth.busy || c.isLoading || purchase.submitting} aria-describedby={id} onClick={async () => {
      setError("");
      try { await auth.logout(); onNavigate?.(); router.replace("/login"); }
      catch (error) { setError(error instanceof Error ? error.message : "Chưa đăng xuất được. Hãy thử lại."); }
    }}><AccountIcon name="logout" /><span>{auth.busy ? "Đang đăng xuất…" : "Đăng xuất"}</span></button>
    <p id={id} role="status">{auth.user ? (c.isLoading || purchase.submitting ? "Chờ xử lý hoàn tất trước khi đăng xuất." : `Đã đăng nhập · ${auth.user.email}`) : auth.ready ? "Phiên khách · Chưa đăng nhập." : "Đang kiểm tra phiên đăng nhập…"}</p>
    {error && <p role="alert" className="error">{error}</p>}
  </div>;
}

export function AccountQuickLinks({ activeView, onNavigate }: { activeView?: AccountView | "orders"; onNavigate: () => void }) {
  return <nav className="account-quick-links" aria-label="Menu tài khoản">
    <Link href="/account" aria-current={activeView === "profile" ? "page" : undefined} onClick={onNavigate}><AccountIcon name="user" /><span>Hồ sơ cá nhân</span></Link>
    <Link href="/orders" aria-current={activeView === "orders" ? "page" : undefined} onClick={onNavigate}><AccountIcon name="orders" /><span>Đơn hàng</span></Link>
    <Link href="/account/conversations" aria-current={activeView === "history" ? "page" : undefined} onClick={onNavigate}><AccountIcon name="history" /><span>Lịch sử hội thoại</span></Link>
    <AccountAuthLinks onNavigate={onNavigate} />
    <AccountLogout onNavigate={onNavigate} />
  </nav>;
}

export function AccountIdentity() {
  const c = useSharedConversation();
  const { user } = useAuth();
  return <div className="account-identity">
    <span className="account-avatar" aria-hidden="true"><AccountIcon name="user" /></span>
    <div><strong>{user?.name ?? "Khách tư vấn"}</strong><span>{user?.email ?? (c.customerPhone || "Chưa cập nhật số điện thoại")}</span><small>{user ? "Đã đăng nhập" : "Phiên khách"}</small></div>
  </div>;
}

export function AccountNavigation({ onNavigate, activeView }: { onNavigate?: () => void; activeView?: AccountView | "orders" }) {
  const groupId = useId();
  const [expanded, setExpanded] = useState(true);
  return <nav className="account-navigation" aria-label="Tài khoản">
    <div className="account-nav-group">
      <button type="button" className="account-nav-toggle" aria-expanded={expanded} aria-controls={groupId} onClick={() => setExpanded(value => !value)}>
        <AccountIcon name="user" /><span>Tài khoản của tôi</span><AccountIcon name="chevron" />
      </button>
      <div id={groupId} className="account-subnav" hidden={!expanded}>
        <Link href="/account" aria-current={activeView === "profile" ? "page" : undefined} onClick={onNavigate}>Hồ sơ cá nhân</Link>
        <Link href="/account/conversations" aria-current={activeView === "history" ? "page" : undefined} onClick={onNavigate}>Lịch sử hội thoại</Link>
      </div>
    </div>
    <Link href="/orders" className="account-orders-link" aria-current={activeView === "orders" ? "page" : undefined} onClick={onNavigate}><AccountIcon name="orders" /><span>Đơn hàng</span><small>Demo</small></Link>
    <AccountAuthLinks onNavigate={onNavigate} />
    <AccountLogout onNavigate={onNavigate} />
  </nav>;
}

function AccountIcon({ name }: { name: "user" | "orders" | "history" | "logout" | "chevron" }) {
  return <svg className={`account-icon account-icon-${name}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "user" ? <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>
      : name === "orders" ? <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V2h6v2M9 10h6M9 15h6" /></>
      : name === "history" ? <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>
      : name === "logout" ? <><path d="M9 4H4v16h5M14 8l4 4-4 4M9 12h12" /></>
      : <path d="m6 9 6 6 6-6" />}
  </svg>;
}

export function GuestProfile({ idPrefix = "customer" }: { idPrefix?: string }) {
  const c = useSharedConversation();
  const { user } = useAuth();
  const purchase = usePurchase();
  const [phone, setPhone] = useState(c.customerPhone);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [allowReset, setAllowReset] = useState(false);
  const changing = phone.trim() !== c.customerPhone;
  const needsReset = changing && (!!c.sessionId || purchase.cart.length > 0 || purchase.orders.length > 0 || !!purchase.delivery.name || !!purchase.buyNow.length);
  return <form className="account-form" noValidate onSubmit={e => {
    e.preventDefault(); setSaved(false);
    if (c.isLoading || !c.sessionReady || !purchase.ready) return;
    if (phone.trim() && !/^(?:0\d{9}|\+84\d{9})$/.test(phone.trim())) { setError("Nhập số điện thoại Việt Nam gồm 10 số hoặc +84."); return; }
    if (needsReset && !allowReset) { setError("Xác nhận bắt đầu phiên khách mới trước khi đổi số."); return; }
    try {
      if (changing) purchase.store.reset();
      c.setCustomerPhone(phone); setError(""); setSaved(true); setAllowReset(false);
    } catch { setError("Chưa xóa được dữ liệu mua sắm cũ. Hãy thử lại trước khi đổi số."); }
  }}>
    <header className="profile-heading"><h2>Hồ sơ cá nhân</h2><p>Quản lý thông tin để Synee tư vấn phù hợp với bạn.</p></header>
    <div className="profile-layout">
      <div className="profile-fields">
        <div className="profile-field profile-readonly"><span>{user ? "Tài khoản" : "Loại hồ sơ"}</span><div><strong>{user?.name ?? "Khách tư vấn"}</strong><small>{user?.email ?? "Đây là thông tin tư vấn trong tab này, không phải tài khoản đăng nhập."}</small></div></div>
        <div className="profile-field">
          <label htmlFor={`${idPrefix}-phone`}>Số điện thoại <span>(không bắt buộc)</span></label>
          <div><input id={`${idPrefix}-phone`} type="tel" autoComplete="tel" maxLength={30} placeholder="VD: 0901234567" value={phone} onChange={e => { setPhone(e.target.value); setSaved(false); }} disabled={c.isLoading || !c.sessionReady} aria-invalid={!!error} aria-describedby={`${idPrefix}-note`} />
            <p id={`${idPrefix}-note`} className="muted-note">Số điện thoại chỉ dùng cho tư vấn. Đổi số sẽ bắt đầu hội thoại mới để tránh lẫn nội dung của hai người.</p></div>
        </div>
        {needsReset && <label className="confirmation"><input className="confirm-profile-reset" type="checkbox" checked={allowReset} onChange={e => setAllowReset(e.target.checked)} disabled={c.isLoading} />Tôi đồng ý xóa hội thoại, bản nháp, giỏ và đơn demo trên thiết bị trước khi đổi số tư vấn.</label>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="profile-save"><button className="commerce-secondary save-profile" disabled={c.isLoading || !c.sessionReady || !purchase.ready} type="submit">Lưu thay đổi</button>
          {saved && <p role="status">Đã lưu thông tin tư vấn trong tab này.</p>}</div>
      </div>
      <aside className="profile-avatar-panel" aria-label="Hồ sơ"><span className="account-avatar" aria-hidden="true"><AccountIcon name="user" /></span><strong>{user?.name ?? "Khách tư vấn"}</strong><span className="profile-guest-badge">{user ? "Đã đăng nhập" : "Phiên khách"}</span></aside>
    </div>
    <details className="profile-session-details"><summary>Thông tin phiên tư vấn</summary>
      <p className="session-id muted-note">Hội thoại: {c.sessionId || "Chưa bắt đầu"}</p>
      <p className="muted-note">{user ? "Hội thoại và bản nháp hiện chỉ giữ khi tab đang mở." : "Hội thoại và bản nháp lưu trong tab này để khôi phục khi tải lại."} File ghi âm chỉ được giữ khi tab đang mở. Dữ liệu đơn demo không được xác minh theo số điện thoại.</p>
    </details>
    {c.sessionNotice && <p role="status">{c.sessionNotice}</p>}
  </form>;
}

function ConversationHistory() {
  const c = useSharedConversation();
  const { user } = useAuth();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);
  const lock = useRef(false);
  return <div className="account-history"><h2>Hội thoại trong tab này</h2>
    <p>{user ? "Hội thoại hiện chỉ giữ khi tab đang mở. Chưa thể tra cứu từ thiết bị khác." : "Đây là bản lưu của phiên khách, không phải lịch sử tài khoản. Chưa thể tra cứu hội thoại từ thiết bị khác."}</p>
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
  return <section className="account-page container" aria-labelledby="account-heading"><h1 id="account-heading">{view === "profile" ? "Tài khoản của tôi" : "Lịch sử hội thoại"}</h1><div className="account-columns"><aside className="commerce-panel account-page-sidebar"><AccountIdentity /><AccountNavigation activeView={view} /></aside><div className="commerce-panel">{!c.sessionReady ? <p role="status">Đang khôi phục thông tin tư vấn…</p> : view === "profile" ? <GuestProfile idPrefix="profile" /> : <ConversationHistory />}</div></div></section>;
}
