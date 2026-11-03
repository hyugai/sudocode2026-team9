"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { applianceSubcategories, categories, filterProducts, productHref, type LiveProductDetails, type ProductCard } from "@/utils/catalog";
import { Asset, ChatPanel } from "./chat-panel";
import { InfoDialog } from "./info-dialog";
import { useSharedConversation } from "./conversation-provider";
import { ProductDetail } from "./product-detail";
import { PurchaseJourney, type PurchaseView } from "./purchase-journey";
import { usePurchase } from "./purchase-provider";
import type { Consultation } from "@/utils/use-conversation";
import { AccountQuickLinks, AccountPage, type AccountView } from "./account-content";

type Dialog = "account" | "support" | null;

export default function Storefront({ product, catalogProducts = [], catalogError = false, initialSearch = "", initialCategory = "Tất cả", view, orderId, accountView }: { product?: LiveProductDetails; catalogProducts?: ProductCard[]; catalogError?: boolean; initialSearch?: string; initialCategory?: string; view?: PurchaseView; orderId?: string; accountView?: AccountView }) {
  const router = useRouter();
  const conversation = useSharedConversation();
  const isCatalog = !product && !view && !accountView;
  const [inlineVisible, setInlineVisible] = useState<boolean | null>(isCatalog ? null : false);
  const [floatingOpen, setFloatingOpen] = useState(false);
  const { voicePreview, setVoicePreview } = conversation;
  const purchase = usePurchase();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [category, setCategory] = useState<string>(categories.some(c => c.name === initialCategory) ? initialCategory : "Tất cả");
  const [subcategory, setSubcategory] = useState("");
  const [query, setQuery] = useState(initialSearch);
  const [search, setSearch] = useState(initialSearch);
  const inlineRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const askRef = useRef<HTMLDivElement>(null);
  const accountRef = useRef<HTMLDivElement>(null);
  const accountTriggerRef = useRef<HTMLButtonElement>(null);
  const accountMenuId = useId();
  const floatingEligible = inlineVisible === false;

  useEffect(() => {
    const target = inlineRef.current;
    if (!target) return;
    const observer = new IntersectionObserver(([entry]) => {
      setInlineVisible(entry.isIntersecting);
      if (entry.isIntersecting) setFloatingOpen(false);
    }, { root: null, threshold: 0, rootMargin: "0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  const closeFloating = () => {
    setFloatingOpen(false);
    requestAnimationFrame(() => (product ? askRef.current?.querySelector<HTMLButtonElement>(".pdp-ask") : launcherRef.current)?.focus({ preventScroll: true }));
  };
  useEffect(() => {
    if (!floatingOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dialog !== "account" && !document.querySelector("dialog[open]")) {
        setFloatingOpen(false);
        requestAnimationFrame(() => (product ? askRef.current?.querySelector<HTMLButtonElement>(".pdp-ask") : launcherRef.current)?.focus({ preventScroll: true }));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [floatingOpen, product, dialog]);

  useEffect(() => {
    if (dialog !== "account") return;
    const closeOutside = (event: Event) => {
      if (event.target instanceof Node && !accountRef.current?.contains(event.target)) setDialog(null);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setDialog(null);
      accountTriggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [dialog]);

  useEffect(() => {
    if (product && floatingOpen && matchMedia("(max-width: 900px)").matches) {
      document.querySelector(".pdp-chat")?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    }
  }, [product, floatingOpen]);

  const returnToChat = () => inlineRef.current?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" });
  const askAboutProduct = (context: Consultation) => {
    if (!product || conversation.isLoading || conversation.audioFile) return;
    conversation.setConsultation(context);
    if (!conversation.input.trim()) conversation.setInput(`Mình muốn được tư vấn về ${context.name} (${context.sku}).`);
    setFloatingOpen(true);
  };
  const selectCategory = (name: string) => { setCategory(name); setSubcategory(""); };
  const openFullChat = (mode: "text" | "realtime") => {
    setVoicePreview(false);
    router.push(`/ai-chat?mode=${mode}`);
  };
  const visibleProducts = filterProducts(category, subcategory, search, catalogProducts);
  const closeDialog = () => {
    setDialog(null);
  };
  const openAccount = () => {
    setDialog("account");
    requestAnimationFrame(() => accountTriggerRef.current?.focus({ preventScroll: true }));
  };

  return <>
    <a className="skip-link" href="#main-content">Đến nội dung chính</a>
    <header className="site-header">
      <div className="header-inner container">
        <div className="header-left"><Link href={isCatalog ? "#main-content" : "/"} aria-label="SUDO CODE — Trang chủ"><Image src="/figma/a-imgSudoCodeOfficialVectorWordmark.svg" alt="SUDO CODE" width={112} height={15.8192} unoptimized /></Link></div>
        <form className="product-search" role="search" onSubmit={e => { e.preventDefault(); if (!isCatalog) { router.push(`/?q=${encodeURIComponent(query.trim())}#catalog`); return; } setSearch(query.trim()); document.getElementById("catalog")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); }}>
          <Asset name="search" /><label htmlFor="product-search" className="sr-only">Tìm sản phẩm, thương hiệu</label><input id="product-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm sản phẩm, thương hiệu…" /><button type="submit"><Asset name="searchPurple" /><span>Tìm</span></button>
        </form>
        <div className="header-right">
          <nav className="utility-nav" aria-label="Hỗ trợ mua sắm"><button onClick={() => setDialog("support")}>Hỗ trợ</button></nav>
          <div className="commerce-actions"><Link href="/cart" className="cart-link" aria-label={`Giỏ hàng demo, ${purchase.cart.reduce((n, l) => n + l.quantity, 0)} sản phẩm`}><Asset name="cart" /><span>Giỏ hàng <span className="cart-count" aria-live="polite">{purchase.cart.reduce((n, l) => n + l.quantity, 0)}</span></span></Link>
            <div className="account-menu" ref={accountRef}>
              <button ref={accountTriggerRef} className="account-trigger" aria-label="Mở menu tài khoản" aria-controls={accountMenuId} aria-expanded={dialog === "account"} onClick={() => setDialog(value => value === "account" ? null : "account")} onKeyDown={event => {
                if (event.key !== "ArrowDown") return;
                event.preventDefault();
                setDialog("account");
                requestAnimationFrame(() => accountRef.current?.querySelector<HTMLAnchorElement>(".account-quick-links a")?.focus());
              }}><Asset name="account" /><span>Tài khoản</span></button>
              {dialog === "account" && <div id={accountMenuId} className="account-popover"><AccountQuickLinks activeView={accountView ?? (view === "orders" ? "orders" : undefined)} onNavigate={() => setDialog(null)} /></div>}
            </div>
          </div>
        </div>
      </div>
    </header>
    <main id="main-content">
      {accountView ? <AccountPage view={accountView} /> : view ? <PurchaseJourney key={`${view}-${orderId ?? ""}`} view={view} orderId={orderId} /> : product ? <div ref={askRef} className={`pdp-layout container${floatingOpen ? " with-consultation" : ""}`}><ProductDetail key={product.sku} product={product} onAsk={askAboutProduct} askDisabled={conversation.isLoading || !!conversation.audioFile} />{floatingOpen && <aside className="pdp-chat" aria-label="Tư vấn sản phẩm cùng Synee"><ChatPanel compact expanded conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onClose={closeFloating} onAccount={openAccount} /></aside>}</div> : <>
      <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-copy"><h1 id="hero-heading">Synee nhớ điều bạn cần, đồng hành đến khi nhận.</h1><p>Tư vấn tận tâm, giao hàng tận tay.</p></div>
        <div ref={inlineRef} className={`inline-chat-mount ${conversation.audioFile ? "has-audio" : ""}`}>
          {inlineVisible !== false && <ChatPanel conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onOpenFullChat={openFullChat} onAccount={openAccount} />}
        </div>
        <a className="browse-action" href="#catalog"><Asset name="down" />Khám phá sản phẩm</a>
      </section>
      <section className="catalog-section" id="catalog" aria-labelledby="catalog-heading">
        <div className="container">
          <div className="section-heading"><h2>Khám phá theo danh mục</h2></div>
          <div className="category-navigation">
            <nav className="category-nav" aria-label="Danh mục sản phẩm">{categories.map(c => <button key={c.name} className={category === c.name ? "active" : ""} aria-pressed={category === c.name} aria-expanded={c.name === "Điện gia dụng" ? category === c.name : undefined} aria-controls={c.name === "Điện gia dụng" ? "appliance-subcategories" : undefined} onClick={() => selectCategory(c.name)}><span><Image src={`/figma/${c.icon}`} width={20} height={20} alt="" unoptimized /></span>{c.name}</button>)}</nav>
            {category === "Điện gia dụng" && <nav id="appliance-subcategories" className="subcategory-nav" aria-label="Danh mục con điện gia dụng">{[{ name: "Tất cả điện gia dụng", value: "" }, ...applianceSubcategories.map(c => ({ name: c.name, value: c.name }))].map(c => <button key={c.value} className={subcategory === c.value ? "active" : ""} aria-pressed={subcategory === c.value} onClick={() => setSubcategory(c.value)}>{c.name}</button>)}</nav>}
          </div>
          <div className="catalog-heading"><div><h2 id="catalog-heading">Gợi ý hôm nay</h2><p>Những món đáng khám phá, theo cách của bạn.</p></div><div className="catalog-sort"><div className="catalog-tabs" role="group" aria-label="Sắp xếp sản phẩm" aria-describedby="catalog-sort-note">{["Dành cho bạn", "Bán chạy", "Mới nhất"].map((s, i) => <button key={s} aria-pressed={i === 0} className={i === 0 ? "active" : ""} disabled={i !== 0} title={i === 0 ? undefined : "Chưa hỗ trợ: chưa có dữ liệu để sắp xếp."}>{i !== 0 && <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="4" y="8" width="12" height="9" rx="2" /><path d="M7 8V5a3 3 0 0 1 6 0v3" /></svg>}<span>{s}</span></button>)}</div><p id="catalog-sort-note" className="catalog-sort-note">Bán chạy và Mới nhất: chưa có dữ liệu để sắp xếp.</p></div></div>
          <p className="catalog-source">Danh mục từ cơ sở dữ liệu · Giá chưa áp dụng khuyến mãi; chưa có ảnh, đánh giá và dữ liệu sắp xếp.</p>
          {catalogError && <p className="empty-catalog" role="alert">Chưa tải được sản phẩm từ backend. Vui lòng thử tải lại trang sau.</p>}
          <p className="filter-status" role="status">{visibleProducts.length} sản phẩm{search ? ` cho “${search}”` : ""}{subcategory ? ` · ${subcategory}` : category !== "Tất cả" ? ` · ${category}` : ""}{(search || category !== "Tất cả") && <> · <button className="text-link" onClick={() => { setSearch(""); setQuery(""); selectCategory("Tất cả"); }}>Xóa bộ lọc</button></>}</p>
          <div className="product-grid">{visibleProducts.map(p => <Link className="product-card" key={p.id} href={productHref(p.id)} aria-label={`${p.name} · ${p.id} · ${p.price}`} data-sku={p.id} data-subcategory={p.subcategory}>
            <div className="product-photo missing-photo"><div><p>Chưa có ảnh BTC</p><p>{p.id}</p></div></div>
            <div className="product-info"><h3>{p.name}</h3><p className="price">{p.price}</p><p className="rating">Chưa có đánh giá / lượt bán</p></div>
          </Link>)}</div>
          {!catalogError && !visibleProducts.length && <p className="empty-catalog">Không tìm thấy sản phẩm. Hãy thử từ khóa khác hoặc hỏi Synee AI.</p>}
        </div>
      </section>
      </>}
    </main>
    <footer className="site-footer"><div className="container">
      <div className="confidence-row">{[{ icon: "shield" as const, title: "An tâm mua sắm", text: "Thông tin rõ ràng, lựa chọn dễ dàng" }, { icon: "truck" as const, title: "Giao hàng tiện lợi", text: "Theo dõi đơn hàng mọi lúc" }, { icon: "companion" as const, title: "AI luôn đồng hành", text: "Tư vấn ngay khi bạn cần" }].map(item => <div key={item.title}><Asset name={item.icon} /><div><strong>{item.title}</strong><p>{item.text}</p></div></div>)}</div>
      <div className="legal-row"><p>© SUDO market · Mua sắm theo cách của bạn</p><div>{["Chính sách bảo mật", "Điều khoản", "Liên hệ"].map(label => <button key={label} onClick={() => setDialog("support")}>{label}</button>)}</div></div>
    </div></footer>
    {floatingEligible && (!product || !floatingOpen) && <>
      {isCatalog && <button className="back-to-ai" onClick={returnToChat}>→ Trở lại trợ lý AI</button>}
      {floatingOpen ? <div className="floating-panel"><ChatPanel compact conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onClose={closeFloating} onAccount={openAccount} /></div>
        : <button ref={launcherRef} className="chat-launcher" aria-label="Trò chuyện với Synee AI" aria-expanded={false} aria-controls="floating-chat" title="Trò chuyện với Synee AI" onClick={() => setFloatingOpen(true)}><Asset name="launcher" /></button>}
    </>}
    {dialog === "support" && <InfoDialog title="Hỗ trợ" onClose={closeDialog}>
      <div><p>Bạn có thể gửi tin nhắn hoặc tải file ghi âm cho Synee AI.</p><p>WAV, MP3, M4A, FLAC, OGG, WebM · tối đa 25 MB / 120 giây. Giới hạn thời lượng do backend kiểm tra.</p><p className="muted-note">Mua sắm dùng dữ liệu BTC tham chiếu; giỏ và đơn là demo trên trình duyệt, không giữ hàng hoặc thu tiền. Chưa kết nối thanh toán, đơn hàng thật và tài khoản khách hàng.</p></div>
    </InfoDialog>}
  </>;
}
