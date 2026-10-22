"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { applianceSubcategories, catalogReferenceDate, categories, filterProducts, productHref, products, type ProductDetails } from "@/utils/catalog";
import { Asset, ChatPanel } from "./chat-panel";
import { InfoDialog } from "./info-dialog";
import { useSharedConversation } from "./conversation-provider";
import { ProductDetail } from "./product-detail";
import { PurchaseJourney, type PurchaseView } from "./purchase-journey";
import { usePurchase } from "./purchase-provider";
import type { Consultation } from "@/utils/use-conversation";

type Dialog = "menu" | "account" | "logs" | "support" | "unavailable" | null;

export default function Storefront({ product, initialSearch = "", view, orderId }: { product?: ProductDetails; initialSearch?: string; view?: PurchaseView; orderId?: string }) {
  const router = useRouter();
  const conversation = useSharedConversation();
  const isCatalog = !product && !view;
  const [inlineVisible, setInlineVisible] = useState<boolean | null>(isCatalog ? null : false);
  const [floatingOpen, setFloatingOpen] = useState(false);
  const { voicePreview, setVoicePreview } = conversation;
  const purchase = usePurchase();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState("");
  const [category, setCategory] = useState<string>("Tất cả");
  const [subcategory, setSubcategory] = useState("");
  const [query, setQuery] = useState(initialSearch);
  const [search, setSearch] = useState(initialSearch);
  const inlineRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
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
    requestAnimationFrame(() => launcherRef.current?.focus({ preventScroll: true }));
  };
  useEffect(() => {
    if (!floatingOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
        setFloatingOpen(false);
        requestAnimationFrame(() => launcherRef.current?.focus({ preventScroll: true }));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [floatingOpen]);

  const unsupported = (message: string) => { setNotice(message); setDialog("unavailable"); };
  const returnToChat = () => inlineRef.current?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" });
  const askAboutProduct = (context: Consultation) => {
    if (!product || conversation.isLoading || conversation.audioFile) return;
    conversation.setConsultation(context);
    if (!conversation.input.trim()) conversation.setInput(`Mình muốn được tư vấn về ${context.name} (${context.sku}).`);
    setFloatingOpen(true);
  };
  const selectCategory = (name: string) => { setCategory(name); setSubcategory(""); };
  const visibleProducts = filterProducts(category, subcategory, search);

  return <>
    <a className="skip-link" href="#main-content">Đến nội dung chính</a>
    <header className="site-header">
      <div className="header-inner container">
        <div className="header-left"><button className="menu-button" aria-label="Mở menu" onClick={() => setDialog("menu")}><Asset name="menu" /></button><Link href={isCatalog ? "#main-content" : "/"} aria-label="SUDO CODE — Trang chủ"><Image src="/figma/a-imgSudoCodeOfficialVectorWordmark.svg" alt="SUDO CODE" width={112} height={15.8192} unoptimized /></Link></div>
        <form className="product-search" role="search" onSubmit={e => { e.preventDefault(); if (!isCatalog) { router.push(`/?q=${encodeURIComponent(query.trim())}#catalog`); return; } setSearch(query.trim()); document.getElementById("catalog")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); }}>
          <Asset name="search" /><label htmlFor="product-search" className="sr-only">Tìm sản phẩm, thương hiệu</label><input id="product-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm sản phẩm, thương hiệu…" /><button type="submit"><Asset name="searchPurple" /><span>Tìm</span></button>
        </form>
        <div className="header-right">
          <nav className="utility-nav" aria-label="Hỗ trợ mua sắm"><button onClick={() => setDialog("support")}>Hỗ trợ</button><Link href="/orders">Theo dõi đơn hàng</Link></nav>
          <div className="commerce-actions"><Link href="/cart" className="cart-link" aria-label={`Giỏ hàng demo, ${purchase.cart.reduce((n, l) => n + l.quantity, 0)} sản phẩm`}><Asset name="cart" /><span>Giỏ hàng <span className="cart-count" aria-live="polite">{purchase.cart.reduce((n, l) => n + l.quantity, 0)}</span></span></Link><button onClick={() => setDialog("account")}><Asset name="account" /><span>Tài khoản</span></button></div>
        </div>
      </div>
    </header>
    <main id="main-content">
      {view ? <PurchaseJourney key={`${view}-${orderId ?? ""}`} view={view} orderId={orderId} /> : product ? <ProductDetail key={product.sku} product={product} onAsk={askAboutProduct} askDisabled={conversation.isLoading || !!conversation.audioFile} /> : <>
      <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-copy"><h1 id="hero-heading">Synee nhớ điều bạn cần, đồng hành đến khi nhận.</h1><p>Tư vấn tận tâm, giao hàng tận tay.</p></div>
        <div ref={inlineRef} className={`inline-chat-mount ${conversation.audioFile ? "has-audio" : ""}`}>
          {inlineVisible !== false && <ChatPanel conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onAccount={() => setDialog("account")} />}
        </div>
        <a className="browse-action" href="#catalog"><Asset name="down" />Khám phá sản phẩm</a>
      </section>
      <section className="catalog-section" id="catalog" aria-labelledby="catalog-heading">
        <div className="container">
          <div className="section-heading"><h2>Khám phá theo danh mục</h2><button className="quiet-button" onClick={() => { selectCategory("Tất cả"); setSearch(""); setQuery(""); }}>Xem tất cả →</button></div>
          <div className="category-navigation">
            <nav className="category-nav" aria-label="Danh mục sản phẩm">{categories.map(c => <button key={c.name} className={category === c.name ? "active" : ""} aria-pressed={category === c.name} aria-expanded={c.name === "Điện gia dụng" ? category === c.name : undefined} aria-controls={c.name === "Điện gia dụng" ? "appliance-subcategories" : undefined} onClick={() => selectCategory(c.name)}><span><Image src={`/figma/${c.icon}`} width={20} height={20} alt="" unoptimized /></span>{c.name}</button>)}</nav>
            {category === "Điện gia dụng" && <nav id="appliance-subcategories" className="subcategory-nav" aria-label="Danh mục con điện gia dụng">{[{ name: "Tất cả điện gia dụng", value: "" }, ...applianceSubcategories.map(c => ({ name: c.name, value: c.name }))].map(c => <button key={c.value} className={subcategory === c.value ? "active" : ""} aria-pressed={subcategory === c.value} onClick={() => setSubcategory(c.value)}>{c.name}</button>)}</nav>}
          </div>
          <div className="catalog-heading"><div><h2 id="catalog-heading">Gợi ý hôm nay</h2><p>Những món đáng khám phá, theo cách của bạn.</p></div><div className="catalog-tabs" role="group" aria-label="Sắp xếp sản phẩm" title="Danh mục chưa có dữ liệu lượt bán và ngày ra mắt để sắp xếp.">{["Dành cho bạn", "Bán chạy", "Mới nhất"].map((s, i) => <button key={s} aria-pressed={i === 0} className={i === 0 ? "active" : ""} disabled={i !== 0}>{s}</button>)}</div></div>
          <p className="catalog-source">Danh mục BTC · Dữ liệu tham chiếu {catalogReferenceDate}. Giá chưa áp dụng khuyến mãi; chưa có ảnh, đánh giá và dữ liệu sắp xếp.</p>
          <p className="filter-status" role="status">{visibleProducts.length} sản phẩm{search ? ` cho “${search}”` : ""}{subcategory ? ` · ${subcategory}` : category !== "Tất cả" ? ` · ${category}` : ""}{(search || category !== "Tất cả") && <> · <button className="text-link" onClick={() => { setSearch(""); setQuery(""); selectCategory("Tất cả"); }}>Xóa bộ lọc</button></>}</p>
          <div className="product-grid">{visibleProducts.map(p => <Link className="product-card" key={p.id} href={productHref(p.id)} aria-label={`${p.name} · ${p.id} · ${p.price}`} data-sku={p.id} data-subcategory={p.subcategory}>
            <div className="product-photo missing-photo"><div><p>Chưa có ảnh BTC</p><p>{p.id}</p></div></div>
            <div className="product-info"><h3>{p.name}</h3><p className="price">{p.price}</p><p className="rating">Chưa có đánh giá / lượt bán</p></div>
          </Link>)}</div>
          {!visibleProducts.length && <p className="empty-catalog">Không tìm thấy sản phẩm. Hãy thử từ khóa khác hoặc hỏi Synee AI.</p>}
          <div className="continue-browsing"><button className="quiet-button" onClick={() => unsupported(`Danh mục BTC có ${products.length} sản phẩm. Hãy xóa bộ lọc để xem tất cả; danh mục trực tiếp chưa được kết nối.`)}><Asset name="more" />Xem thêm sản phẩm</button></div>
        </div>
      </section>
      </>}
    </main>
    <footer className="site-footer"><div className="container">
      <div className="confidence-row">{[{ icon: "shield" as const, title: "An tâm mua sắm", text: "Thông tin rõ ràng, lựa chọn dễ dàng" }, { icon: "truck" as const, title: "Giao hàng tiện lợi", text: "Theo dõi đơn hàng mọi lúc" }, { icon: "companion" as const, title: "AI luôn đồng hành", text: "Tư vấn ngay khi bạn cần" }].map(item => <div key={item.title}><Asset name={item.icon} /><div><strong>{item.title}</strong><p>{item.text}</p></div></div>)}</div>
      <div className="legal-row"><p>© SUDO market · Mua sắm theo cách của bạn</p><div>{["Chính sách bảo mật", "Điều khoản", "Liên hệ"].map(label => <button key={label} onClick={() => setDialog("support")}>{label}</button>)}</div></div>
    </div></footer>
    {floatingEligible && <>
      {isCatalog && <button className="back-to-ai" onClick={returnToChat}>→ Trở lại trợ lý AI</button>}
      {floatingOpen ? <div className="floating-panel"><ChatPanel compact conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onClose={closeFloating} onAccount={() => setDialog("account")} /></div>
        : <button ref={launcherRef} className="chat-launcher" aria-label="Trò chuyện với Synee AI" aria-expanded={false} aria-controls="floating-chat" title="Trò chuyện với Synee AI" onClick={() => setFloatingOpen(true)}><Asset name="launcher" /></button>}
    </>}
    {dialog && <InfoDialog title={dialog === "menu" ? "SUDO CODE" : dialog === "logs" ? "Nhật ký hội thoại" : dialog === "account" ? "Thông tin hội thoại" : dialog === "support" ? "Hỗ trợ" : "Thông tin"} onClose={() => setDialog(null)}>
      {dialog === "menu" && <nav className="menu-links"><button onClick={() => { setDialog(null); if (!isCatalog) setFloatingOpen(true); else returnToChat(); }}>Trò chuyện với Synee AI</button><Link href={isCatalog ? "#catalog" : "/#catalog"} onClick={() => setDialog(null)}>Khám phá sản phẩm</Link><Link href="/cart">Giỏ hàng demo</Link><Link href="/orders">Đơn hàng demo</Link><button onClick={() => setDialog("account")}>Thông tin khách hàng</button><button onClick={() => setDialog("logs")}>Nhật ký hội thoại</button><button disabled>Analytics (sắp có)</button></nav>}
      {dialog === "account" && <div className="account-form"><p>Nhập số điện thoại để Synee nhận diện khách hàng khi tư vấn.</p><label htmlFor="customer-phone">Số điện thoại khách hàng</label><input id="customer-phone" type="tel" autoComplete="tel" placeholder="VD: 0984726714" value={conversation.customerPhone} onChange={e => conversation.setCustomerPhone(e.target.value)} disabled={conversation.isLoading} /><p className="session-id">Hội thoại: {conversation.sessionId || "Chưa bắt đầu"}</p><p className="muted-note">Đăng nhập và khôi phục hội thoại cũ chưa được kết nối. Hội thoại hiện tại được giữ khi chuyển giữa chat trên trang và chat thu gọn, cho đến khi tải lại trang.</p></div>}
      {dialog === "support" && <div><p>Bạn có thể gửi tin nhắn hoặc tải file ghi âm cho Synee AI.</p><p>WAV, MP3, M4A, FLAC, OGG, WebM · tối đa 25 MB / 120 giây. Giới hạn thời lượng do backend kiểm tra.</p><p className="muted-note">Mua sắm dùng dữ liệu BTC tham chiếu; giỏ và đơn là demo trên trình duyệt, không giữ hàng hoặc thu tiền. Chưa kết nối thanh toán, đơn hàng thật và tài khoản khách hàng.</p></div>}
      {dialog === "unavailable" && <p>{notice}</p>}
      {dialog === "logs" && <div className="debug-logs"><p>Thông tin chẩn đoán do backend cung cấp; chỉ xuất hiện khi backend bật phản hồi debug.</p>{!conversation.debugLogs.length ? <p>Chưa có log nào. Hãy bắt đầu trò chuyện để ghi log.</p> : conversation.debugLogs.map((log, i) => <article key={i}><h3>Lượt {i + 1}: {log.userMessage}</h3><p>Intent: {log.debug.intent}</p><h4>Kiến thức liên quan</h4><pre>{JSON.stringify(log.debug.retrieved_knowledge, null, 2)}</pre>{log.debug.steps?.map((step, j) => <div key={j}><strong>{step.action}{step.tool ? ` · ${step.tool}` : ""}</strong><p>{step.rationale}</p></div>)}<details><summary>Chi tiết phản hồi debug</summary><pre>{JSON.stringify(log.debug, null, 2)}</pre></details></article>)}</div>}
    </InfoDialog>}
  </>;
}
