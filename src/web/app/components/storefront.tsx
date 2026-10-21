"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { useConversation } from "@/utils/use-conversation";
import { categories, products } from "@/utils/catalog";
import { Asset, ChatPanel } from "./chat-panel";
import { InfoDialog } from "./info-dialog";

type Dialog = "menu" | "account" | "logs" | "support" | "unavailable" | null;

export default function Storefront() {
  const conversation = useConversation();
  const [inlineVisible, setInlineVisible] = useState<boolean | null>(null);
  const [floatingOpen, setFloatingOpen] = useState(false);
  const [voicePreview, setVoicePreview] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState("");
  const [category, setCategory] = useState<string>("Tất cả");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("Dành cho bạn");
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
  const askAbout = (name: string, price: string) => {
    if (conversation.isLoading || conversation.audioFile) return;
    conversation.setInput(`Mình muốn được tư vấn về ${name} (${price}).`);
    if (floatingEligible) setFloatingOpen(true);
    else { returnToChat(); requestAnimationFrame(() => inlineRef.current?.querySelector("textarea")?.focus({ preventScroll: true })); }
  };
  const visibleProducts = products.filter(p => (category === "Tất cả" || p.category === category) && p.name.toLocaleLowerCase("vi").includes(search.toLocaleLowerCase("vi")));
  if (sort === "Bán chạy") visibleProducts.sort((a, b) => {
    const sold = (rating: string) => { const text = rating.split("Đã bán ")[1]; return parseFloat(text.replace(",", ".")) * (text.includes("k") ? 1000 : 1); };
    return sold(b.rating) - sold(a.rating);
  });
  if (sort === "Mới nhất") visibleProducts.reverse();

  return <>
    <a className="skip-link" href="#main-content">Đến nội dung chính</a>
    <header className="site-header">
      <div className="header-inner container">
        <div className="header-left"><button className="menu-button" aria-label="Mở menu" onClick={() => setDialog("menu")}><Asset name="menu" /></button><a href="#main-content" aria-label="SUDO CODE — Trang chủ"><Image src="/figma/a-imgSudoCodeOfficialVectorWordmark.svg" alt="SUDO CODE" width={112} height={15.8192} unoptimized /></a></div>
        <form className="product-search" role="search" onSubmit={e => { e.preventDefault(); setSearch(query.trim()); document.getElementById("catalog")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); }}>
          <Asset name="search" /><label htmlFor="product-search" className="sr-only">Tìm sản phẩm, thương hiệu</label><input id="product-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm sản phẩm, thương hiệu…" /><button type="submit"><Asset name="searchPurple" /><span>Tìm</span></button>
        </form>
        <div className="header-right">
          <nav className="utility-nav" aria-label="Hỗ trợ mua sắm"><button onClick={() => setDialog("support")}>Hỗ trợ</button><button onClick={() => unsupported("Theo dõi đơn hàng chưa được kết nối trong phiên bản này. Bạn có thể nhờ Synee tư vấn trong cuộc trò chuyện.")}>Theo dõi đơn hàng</button></nav>
          <div className="commerce-actions"><button onClick={() => unsupported("Giỏ hàng và thanh toán chưa được kết nối. Danh mục hiện hiển thị sản phẩm minh họa từ thiết kế.")}><Asset name="cart" /><span>Giỏ hàng</span></button><button onClick={() => setDialog("account")}><Asset name="account" /><span>Tài khoản</span></button></div>
        </div>
      </div>
    </header>
    <main id="main-content">
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
          <div className="section-heading"><h2>Khám phá theo danh mục</h2><button className="quiet-button" onClick={() => { setCategory("Tất cả"); setSearch(""); setQuery(""); }}>Xem tất cả →</button></div>
          <nav className="category-nav" aria-label="Danh mục sản phẩm">{categories.map(c => <button key={c.name} className={category === c.name ? "active" : ""} aria-pressed={category === c.name} onClick={() => setCategory(c.name)}><span><Image src={`/figma/${c.icon}`} width={20} height={20} alt="" unoptimized /></span>{c.name}</button>)}</nav>
          <div className="catalog-heading"><div><h2 id="catalog-heading">Gợi ý hôm nay</h2><p>Những món đáng khám phá, theo cách của bạn.</p></div><div className="catalog-tabs" role="group" aria-label="Sắp xếp sản phẩm minh họa">{["Dành cho bạn", "Bán chạy", "Mới nhất"].map(s => <button key={s} aria-pressed={sort === s} className={sort === s ? "active" : ""} onClick={() => setSort(s)}>{s}</button>)}</div></div>
          {(search || category !== "Tất cả") && <p className="filter-status" role="status">{visibleProducts.length} sản phẩm minh họa{search ? ` cho “${search}”` : ""} · <button className="text-link" onClick={() => { setSearch(""); setQuery(""); setCategory("Tất cả"); }}>Xóa bộ lọc</button></p>}
          <div className="product-grid">{visibleProducts.map(p => <article className="product-card" key={p.id}>
            <div className="product-photo"><Image src={`/figma/${p.image}`} alt={p.name} fill sizes="(max-width: 600px) 45vw, (max-width: 1000px) 30vw, 224px" unoptimized /></div>
            <div className="product-info"><h3>{p.name}</h3><p className="price">{p.price}</p><p className="rating"><Asset name="star" />{p.rating}</p><button className="ask-product" disabled={conversation.isLoading || !!conversation.audioFile} title={conversation.audioFile ? "Bỏ ghi âm để đặt câu hỏi về sản phẩm" : conversation.isLoading ? "Đang chờ phản hồi từ Synee AI" : undefined} onClick={() => askAbout(p.name, p.price)}><Asset name="sparkle" />Hỏi AI về sản phẩm</button></div>
          </article>)}</div>
          {!visibleProducts.length && <p className="empty-catalog">Không tìm thấy sản phẩm trong danh mục minh họa. Hãy thử từ khóa khác hoặc hỏi Synee AI.</p>}
          <div className="continue-browsing"><button className="quiet-button" onClick={() => unsupported("Đã hiển thị toàn bộ 10 sản phẩm minh họa trong thiết kế. Danh mục trực tiếp cần được kết nối với dịch vụ sản phẩm.")}><Asset name="more" />Xem thêm sản phẩm</button></div>
        </div>
      </section>
    </main>
    <footer className="site-footer"><div className="container">
      <div className="confidence-row">{[{ icon: "shield" as const, title: "An tâm mua sắm", text: "Thông tin rõ ràng, lựa chọn dễ dàng" }, { icon: "truck" as const, title: "Giao hàng tiện lợi", text: "Theo dõi đơn hàng mọi lúc" }, { icon: "companion" as const, title: "AI luôn đồng hành", text: "Tư vấn ngay khi bạn cần" }].map(item => <div key={item.title}><Asset name={item.icon} /><div><strong>{item.title}</strong><p>{item.text}</p></div></div>)}</div>
      <div className="legal-row"><p>© SUDO market · Mua sắm theo cách của bạn</p><div>{["Chính sách bảo mật", "Điều khoản", "Liên hệ"].map(label => <button key={label} onClick={() => setDialog("support")}>{label}</button>)}</div></div>
    </div></footer>
    {floatingEligible && <>
      <button className="back-to-ai" onClick={returnToChat}>→ Trở lại trợ lý AI</button>
      {floatingOpen ? <div className="floating-panel"><ChatPanel compact conversation={conversation} voicePreview={voicePreview} onModeChange={setVoicePreview} onClose={closeFloating} onAccount={() => setDialog("account")} /></div>
        : <button ref={launcherRef} className="chat-launcher" aria-label="Trò chuyện với Synee AI" aria-expanded={false} aria-controls="floating-chat" title="Trò chuyện với Synee AI" onClick={() => setFloatingOpen(true)}><Asset name="launcher" /></button>}
    </>}
    {dialog && <InfoDialog title={dialog === "menu" ? "SUDO CODE" : dialog === "logs" ? "Nhật ký hội thoại" : dialog === "account" ? "Thông tin hội thoại" : dialog === "support" ? "Hỗ trợ" : "Thông tin"} onClose={() => setDialog(null)}>
      {dialog === "menu" && <nav className="menu-links"><button onClick={() => { setDialog(null); returnToChat(); }}>Trò chuyện với Synee AI</button><a href="#catalog" onClick={() => setDialog(null)}>Khám phá sản phẩm</a><button onClick={() => setDialog("account")}>Thông tin khách hàng</button><button onClick={() => setDialog("logs")}>Nhật ký hội thoại</button><button disabled>Analytics (sắp có)</button></nav>}
      {dialog === "account" && <div className="account-form"><p>Nhập số điện thoại để Synee nhận diện khách hàng khi tư vấn.</p><label htmlFor="customer-phone">Số điện thoại khách hàng</label><input id="customer-phone" type="tel" autoComplete="tel" placeholder="VD: 0984726714" value={conversation.customerPhone} onChange={e => conversation.setCustomerPhone(e.target.value)} disabled={conversation.isLoading} /><p className="session-id">Hội thoại: {conversation.sessionId || "Chưa bắt đầu"}</p><p className="muted-note">Đăng nhập và khôi phục hội thoại cũ chưa được kết nối. Hội thoại hiện tại được giữ khi chuyển giữa chat trên trang và chat thu gọn, cho đến khi tải lại trang.</p></div>}
      {dialog === "support" && <div><p>Bạn có thể gửi tin nhắn hoặc tải file ghi âm cho Synee AI.</p><p>WAV, MP3, M4A, FLAC, OGG, WebM · tối đa 25 MB / 120 giây. Giới hạn thời lượng do backend kiểm tra.</p><p className="muted-note">Danh mục và thông tin mua sắm hiện là nội dung minh họa từ thiết kế. Chưa có dịch vụ giỏ hàng, thanh toán hoặc tài khoản khách hàng.</p></div>}
      {dialog === "unavailable" && <p>{notice}</p>}
      {dialog === "logs" && <div className="debug-logs"><p>Thông tin chẩn đoán do backend cung cấp; chỉ xuất hiện khi backend bật phản hồi debug.</p>{!conversation.debugLogs.length ? <p>Chưa có log nào. Hãy bắt đầu trò chuyện để ghi log.</p> : conversation.debugLogs.map((log, i) => <article key={i}><h3>Lượt {i + 1}: {log.userMessage}</h3><p>Intent: {log.debug.intent}</p><h4>Kiến thức liên quan</h4><pre>{JSON.stringify(log.debug.retrieved_knowledge, null, 2)}</pre>{log.debug.steps?.map((step, j) => <div key={j}><strong>{step.action}{step.tool ? ` · ${step.tool}` : ""}</strong><p>{step.rationale}</p></div>)}<details><summary>Chi tiết phản hồi debug</summary><pre>{JSON.stringify(log.debug, null, 2)}</pre></details></article>)}</div>}
    </InfoDialog>}
  </>;
}
