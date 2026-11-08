"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import VoicePanel from "@/components/voice-panel";
import { apiBase } from "@/utils/use-conversation";
import { useSharedConversation } from "../components/conversation-provider";
import { GuestProfile } from "../components/account-content";
import { InfoDialog } from "../components/info-dialog";
import { Icon } from "./icons";
import { ReplyFeedback, ReplyFeedbackProvider } from "./reply-feedback";
import { CallBriefPanel } from "./call-brief-panel";

export type AiChatMode = "text" | "realtime";
type Dialog = "history" | "details" | "profile" | "new" | null;
const modes = [
  ["text", "message", "Chat"],
  ["realtime", "mic", "Voice"],
] as const;
const suggestions = [
  { icon: "compare", title: "So sánh lựa chọn", detail: "Phân tích ưu, nhược điểm rõ ràng", text: "Hãy giúp mình so sánh các sản phẩm phù hợp." },
  { icon: "spark", title: "Gợi ý theo nhu cầu", detail: "Tìm phương án vừa ngân sách", text: "Mình muốn tìm tai nghe không dây dưới 3 triệu." },
  { icon: "plan", title: "Lập kế hoạch mua sắm", detail: "Tạo danh sách theo ưu tiên", text: "Giúp mình lên danh sách mua sắm theo nhu cầu và ngân sách." },
] as const;

export function AiChatExperience({ mode }: { mode: AiChatMode }) {
  const voiceMode = mode === "realtime";
  const c = useSharedConversation();
  const router = useRouter();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [resetError, setResetError] = useState("");
  const [feedbackRevision, setFeedbackRevision] = useState(0);
  const resetLock = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const busy = c.isLoading || !c.sessionReady;
  const canSend = !busy && !c.conversationEnded && c.backendReady && c.cooldownSeconds === 0 && (!!c.input.trim() || !!c.audioFile);
  const title = c.messages.find(message => message.role === "user")?.text || "Cuộc trò chuyện mới";
  const query = search.trim().toLocaleLowerCase("vi");
  const visibleMessages = c.messages.map((message, index) => ({ ...message, index }))
    .filter(message => !query || message.text.toLocaleLowerCase("vi").includes(query));
  const hint = c.errorMessage || (c.cooldownSeconds > 0
    ? `Có thể gửi tiếp sau ${c.cooldownSeconds} giây.`
    : !c.sessionReady ? "Đang khôi phục hội thoại…"
    : c.conversationEnded ? "Hội thoại đã kết thúc. Chọn Cuộc trò chuyện mới để tiếp tục."
    : c.voiceActive ? "Kết thúc phiên voice trước khi gửi tin nhắn hoặc ghi âm."
    : c.isLoading ? (c.audioFile ? "Đang nhận dạng ghi âm và chờ phản hồi…" : "Đang chờ phản hồi…")
    : !c.backendReady ? "Backend chưa sẵn sàng. Hệ thống đang kiểm tra lại; nội dung vẫn được giữ."
    : c.audioFile ? "Gửi ghi âm để chuyển thành văn bản và nhận phản hồi. Tối đa 25 MB / 120 giây."
    : "");

  useEffect(() => {
    const history = historyRef.current;
    if (history && !query) history.scrollTop = history.scrollHeight;
  }, [c.messages, c.isLoading, query, mode]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (input) {
      input.style.height = "27px";
      input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    }
  }, [c.input, mode]);

  const switchMode = (next: AiChatMode) => {
    if (next === mode || (c.isLoading && !c.voiceActive)) return;
    setDialog(null);
    router.replace(`/ai-chat?mode=${next}`, { scroll: false });
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setNotice("Đã sao chép nội dung."); }
    catch { setNotice("Chưa sao chép được. Hãy chọn nội dung và sao chép thủ công."); }
  };
  const exportConversation = () => {
    const text = c.messages.map(message => `${message.role === "user" ? "Bạn" : "Synee AI"}: ${message.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = "hoi-thoai-synee.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Đã xuất hội thoại thành tệp văn bản.");
  };
  const startNew = async () => {
    if (resetLock.current || busy) return;
    resetLock.current = true;
    setResetError("");
    try {
      await c.endConversation();
      setFeedbackRevision(previous => previous + 1);
      setSearch(""); setNotice(""); setDialog(null);
      inputRef.current?.focus();
    } catch (error) {
      setResetError(error instanceof Error ? error.message : "Chưa bắt đầu được hội thoại mới. Hãy thử lại.");
    } finally { resetLock.current = false; }
  };

  const sidebar = <>
    <button className="ai-new-chat" disabled={busy} onClick={() => { setResetError(""); setDialog("new"); }}><Icon name="plus" />Cuộc trò chuyện mới</button>
    <label className="ai-search"><span className="sr-only">Tìm trong hội thoại</span><Icon name="search" />
      <input ref={searchRef} value={search} onChange={event => setSearch(event.target.value)} placeholder="Tìm trong hội thoại" type="search" />
    </label>
    <div className="ai-history-heading"><span>Trong tab này</span></div>
    <nav className="ai-conversation-list" aria-label="Hội thoại hiện tại">
      <button className="active" onClick={() => { setDialog(null); historyRef.current?.focus(); }} aria-current="page">
        <span className="ai-conversation-icon"><Icon name="chat" /></span>
        <span><strong>{title}</strong><small>{c.messages.length} tin nhắn · phiên hiện tại</small></span>
      </button>
      {search && <button className="ai-search-results" onClick={() => { setDialog(null); historyRef.current?.focus(); }}>{visibleMessages.length} tin nhắn phù hợp · Xem kết quả</button>}
    </nav>
    <div className="ai-sidebar-footer"><button onClick={() => setDialog("profile")} disabled={busy}>
      <span className="ai-user-avatar">KH</span><span><strong>{c.customerPhone || "Khách tư vấn"}</strong><small>Thông tin tư vấn</small></span><Icon name="chevron" />
    </button></div>
  </>;
  const details = <CallBriefPanel brief={c.callBrief} loading={c.isLoading && !c.voiceActive} error={c.callBriefStale} hasConversation={c.messages.length > 1}>
    <p className="ai-session-id">Hội thoại: {c.sessionId || "Chưa bắt đầu"}</p>
      <p>{c.customerPhone || "Chưa cung cấp số điện thoại"}</p>
      <button className="ai-add-source" disabled={busy} onClick={() => setDialog("profile")}>Cập nhật thông tin tư vấn</button>
    <div className="ai-note">
      <p>{c.consultation ? `${c.consultation.name} · ${c.consultation.sku} · ${c.consultation.price} · SL ${c.consultation.quantity}` : "Bạn có thể chọn sản phẩm trên dashboard để được tư vấn cụ thể."}</p>
      {c.consultation && <button disabled={busy} onClick={() => c.setConsultation(null)}>Bỏ ngữ cảnh sản phẩm</button>}
    </div><Link href="/#catalog" className="ai-add-source">Xem danh mục sản phẩm<Icon name="arrowUpRight" /></Link>
    <Link href="/account/conversations" className="ai-add-source">Lịch sử & nhật ký chẩn đoán</Link>
  </CallBriefPanel>;

  const modeControls = <div className="ai-mode-bar" data-mode={mode} role="group" aria-label="Chế độ hội thoại">{modes.map(([value, icon, label]) =>
    <button key={value} aria-pressed={mode === value} className={mode === value ? "active" : ""} disabled={c.isLoading && !c.voiceActive} onClick={() => switchMode(value)}><Icon name={icon} />{label}</button>
  )}</div>;

  return <>
    <a className="skip-link" href={voiceMode ? "#ai-voice-session" : "#ai-message"}>{voiceMode ? "Đến cuộc trò chuyện voice" : "Đến ô nhập tin nhắn"}</a>
    <main className={`ai-workspace${voiceMode ? " ai-voice-workspace" : ""}`} aria-labelledby="ai-workspace-title">
      <header className={`ai-topbar${voiceMode ? " ai-voice-header" : ""}`}>
        <div className="ai-header-brand">
          <span className="ai-brand-mark"><Icon name="spark" /></span>
          <div><h1 id="ai-workspace-title">Synee AI</h1><p>Trợ lý mua sắm</p></div>
        </div>
        {modeControls}
        {!voiceMode && <button className="ai-icon-button ai-menu-trigger" aria-label="Mở lịch sử" onClick={() => setDialog("history")}><Icon name="menu" /></button>}
        <div className="ai-topbar-actions">
          {!voiceMode && <button className="ai-icon-button" aria-label="Xuất hội thoại" onClick={exportConversation}><Icon name="share" /></button>}
          {!voiceMode && <button className="ai-detail-button" aria-label="Mở call brief" onClick={() => setDialog("details")}><Icon name="panel" /><span>Call brief</span></button>}
          <Link href="/" className="ai-exit-link" aria-label="Trở lại dashboard"><Icon name="arrowLeft" /><span>Dashboard</span></Link>
        </div>
      </header>
      {!voiceMode && <aside className="ai-sidebar" aria-label="Lịch sử hội thoại">{sidebar}</aside>}
      <section className="ai-main-shell">
        {voiceMode ? <section id="ai-voice-session" className="ai-voice-session" aria-label="Trò chuyện voice cùng Synee AI" tabIndex={-1}>
          <VoicePanel apiBase={apiBase} customerPhone={c.customerPhone} onActiveChange={c.setVoiceActive} />
        </section> : <div className="ai-content-row">
          <section className="ai-chat-stage" aria-label="Trò chuyện cùng Synee AI">
            <div className="ai-message-scroll" ref={historyRef} tabIndex={0} aria-label="Nội dung trò chuyện">
              {c.messages.length === 1 && !query && <div className="ai-thread-intro"><span className="ai-thread-icon"><Icon name="spark" /></span><h2>Bắt đầu cùng Synee AI</h2><p>Không gian riêng để bạn trò chuyện, tìm hiểu và lựa chọn.</p></div>}
              <ReplyFeedbackProvider key={`${c.sessionId}:${c.customerPhone}:${feedbackRevision}`}><div className="ai-message-list" role="log" aria-live="polite" aria-relevant="additions text" aria-label="Tin nhắn cùng Synee">
                {visibleMessages.map(message => <article key={message.index} className={`ai-message ${message.role === "agent" ? "assistant" : "user"}`}>
                  {message.role === "agent" && <span className="ai-avatar"><Icon name="spark" /></span>}
                  <div><div className="ai-message-meta"><strong>{message.role === "agent" ? "Synee AI" : "Bạn"}</strong></div><div className="ai-bubble">{message.text}</div>
                    {message.role === "agent" ? <ReplyFeedback message={c.messages[message.index]} messageNumber={message.index + 1} onCopy={() => void copy(message.text)} disabled={!c.sessionReady} /> : <div className="ai-message-tools"><button type="button" aria-label={`Sao chép tin nhắn ${message.index + 1}`} onClick={() => void copy(message.text)}><Icon name="copy" /></button></div>}
                  </div>
                </article>)}
                {c.isLoading && !c.voiceActive && <article className="ai-message assistant"><span className="ai-avatar"><Icon name="spark" /></span><div className="ai-thinking" role="status" aria-label="Synee đang xử lý"><i /><i /><i /></div></article>}
              </div></ReplyFeedbackProvider>
              {query && <p className="ai-search-summary" role="status">{visibleMessages.length} tin nhắn phù hợp. <button className="text-link" onClick={() => setSearch("")}>Xóa tìm kiếm</button></p>}
              {c.messages.length === 1 && mode === "text" && !query && <div className="ai-suggestion-grid">{suggestions.map(item =>
                <button key={item.title} disabled={busy || !!c.audioFile} onClick={() => { c.setInput(item.text); inputRef.current?.focus(); }}><span><Icon name={item.icon} /></span><strong>{item.title}</strong><small>{item.detail}</small><Icon name="arrowUpRight" /></button>
              )}</div>}
            </div>
            <div className="ai-composer-wrap">
              {c.consultation && <div className="ai-context" role="status">Tư vấn: {c.consultation.name}. {c.audioFile ? "Ngữ cảnh sản phẩm chỉ gửi kèm tin nhắn văn bản." : "Ngữ cảnh sẽ gửi kèm tin nhắn."}</div>}
              <div id="ai-send-status" className="ai-feedback" aria-live="polite">{hint && <p className={c.errorMessage ? "error" : ""} role={c.errorMessage ? "alert" : "status"}>{hint}</p>}</div>
              {(notice || c.sessionNotice) && <p className="ai-feedback" role="status">{notice || c.sessionNotice}</p>}
              <form className="ai-composer" onSubmit={event => { event.preventDefault(); if (canSend) void c.sendMessage(); }}>
                <label className="sr-only" htmlFor="ai-message">Tin nhắn cho Synee AI</label>
                <textarea id="ai-message" ref={inputRef} value={c.input} disabled={busy || !!c.audioFile} aria-describedby="ai-send-status" onChange={event => c.setInput(event.target.value)} rows={1} placeholder={c.audioFile ? "Đã chọn ghi âm cho lượt thoại này" : "Nhập câu hỏi cho Synee AI…"} onKeyDown={event => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (canSend) void c.sendMessage(); }
                }} />
                {c.audioFile && <div className="audio-preview"><div><span>{c.audioFile.name}</span><button type="button" disabled={busy} onClick={c.clearAudio}>Bỏ ghi âm</button></div>{c.audioPreviewUrl && <audio controls preload="metadata" src={c.audioPreviewUrl} aria-label="Nghe lại ghi âm" />}</div>}
                <input ref={fileRef} className="sr-only" tabIndex={-1} type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.webm,audio/*" aria-label="Chọn file ghi âm" disabled={busy} onChange={event => {
                  const file = event.target.files?.[0];
                  if (file) c.selectAudio(file);
                  event.target.value = "";
                }} />
                <div className="ai-composer-actions"><div><button type="button" aria-label="Tải file audio" title="Tải file audio · Tối đa 25 MB / 120 giây" disabled={busy} onClick={() => fileRef.current?.click()}><Icon name="mic" /></button></div>
                  <div><button type="button" className="ai-composer-mic" aria-label="Chuyển sang Voice trực tiếp" title="Chuyển sang Voice trực tiếp" disabled={busy} onClick={() => switchMode("realtime")}><Icon name="mic" /></button><button type="submit" className="ai-send" disabled={!canSend} aria-describedby="ai-send-status" aria-label={c.audioFile ? "Gửi ghi âm" : c.errorMessage ? "Thử lại tin nhắn" : "Gửi tin nhắn"}><Icon name="arrowUp" /></button></div>
                </div>
              </form>
              <p className="ai-disclaimer">Kiểm tra lại thông tin quan trọng trước khi đặt hàng.</p>
            </div>
          </section>
          <aside className="ai-desktop-details" aria-label="Call brief của cuộc tư vấn">{details}</aside>
        </div>}
      </section>
    </main>
    {!voiceMode && <>
    {dialog === "history" && <InfoDialog title="Hội thoại trong tab này" className="ai-history-dialog" onClose={() => setDialog(null)}><div className="ai-sidebar">{sidebar}</div></InfoDialog>}
    {dialog === "details" && <InfoDialog title="Call brief" drawer className="ai-details-dialog" onClose={() => setDialog(null)}>{details}</InfoDialog>}
    {dialog === "profile" && <InfoDialog title="Thông tin tư vấn" drawer onClose={() => setDialog(null)}><GuestProfile idPrefix="ai-customer" /></InfoDialog>}
    {dialog === "new" && <InfoDialog title="Bắt đầu hội thoại mới" onClose={() => { if (!busy) setDialog(null); }}>
      <p>{c.accountMode ? "Hội thoại sẽ được kết thúc và giữ trong lịch sử tài khoản. Bản nháp và ghi âm hiện tại sẽ được xóa khỏi tab này." : "Hội thoại, bản nháp và ghi âm hiện tại sẽ được xóa khỏi tab này."} Thông tin tư vấn vẫn được giữ.</p>
      <p>Bạn có thể xuất hội thoại trước khi tiếp tục.</p>
      <div className="ai-reset-actions"><button className="commerce-secondary" disabled={busy} onClick={exportConversation}>Xuất hội thoại</button><button className="commerce-secondary" disabled={busy} onClick={() => void startNew()}>{c.isLoading ? "Đang kết thúc…" : "Bắt đầu mới"}</button></div>
      {resetError && <p className="error" role="alert">{resetError}</p>}
    </InfoDialog>}
    </>}
  </>;
}
