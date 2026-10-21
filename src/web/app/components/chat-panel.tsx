"use client";

import Image from "next/image";
import { useEffect, useLayoutEffect, useRef } from "react";
import type { Conversation } from "@/utils/use-conversation";

const paths = {
  search: "a-imgFrame.svg", searchPurple: "a-imgFrame1.svg", menu: "a-imgMenuOfficialThreeLineGlyph.svg",
  cart: "a-imgFrame2.svg", account: "a-imgVectorUser.svg", sparkle: "a-imgFrame3.svg",
  attach: "a-imgVectorAttach.svg", send: "a-imgVectorSend.svg", down: "a-imgFrame4.svg",
  star: "a-imgFrame11.svg", more: "a-imgFrame12.svg", shield: "a-imgVectorShield.svg",
  truck: "a-imgFrame13.svg", companion: "a-imgFrame14.svg", close: "c-imgVectorClose.svg",
  compactAttach: "c-imgVectorAttach.svg", compactSend: "c-imgVectorSend.svg", compactSparkle: "c-imgFrame.svg",
  launcher: "launcher-imgVectorChat.svg",
} as const;

/** Preserve exported SVG geometry within the design's icon slots. */
export function Asset({ name, className = "" }: { name: keyof typeof paths; className?: string }) {
  const width = name === "launcher" ? 24 : name === "menu" ? 21 : name === "compactSend" ? 16 : 20;
  return <Image className={`asset ${className}`} src={`/figma/${paths[name]}`} width={width} height={name === "menu" ? 15 : width} alt="" aria-hidden="true" unoptimized />;
}

interface Props {
  conversation: Conversation;
  compact?: boolean;
  voicePreview: boolean;
  onModeChange: (voice: boolean) => void;
  onClose?: () => void;
  onAccount: () => void;
}

export function ChatPanel({ conversation: c, compact = false, voicePreview, onModeChange, onClose, onAccount }: Props) {
  const historyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const prefix = compact ? "floating" : "inline";
  const statusId = `${prefix}-status`;
  useEffect(() => {
    const history = historyRef.current;
    if (history) history.scrollTop = history.scrollHeight;
  }, [c.messages, c.isLoading]);
  useEffect(() => { if (compact) inputRef.current?.focus({ preventScroll: true }); }, [compact]);
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (input) { input.style.height = "22px"; input.style.height = `${Math.min(input.scrollHeight, 66)}px`; }
  }, [c.input]);
  const disabled = c.isLoading || !c.backendReady || c.cooldownSeconds > 0 || (!c.input.trim() && !c.audioFile);
  const prompts = compact
    ? [{ label: "So sánh nhanh", text: "Hãy giúp mình so sánh các sản phẩm phù hợp." }, { label: "Xem gợi ý", text: "Gợi ý sản phẩm phù hợp với nhu cầu của mình." }]
    : [{ label: "Tai nghe dưới 3 triệu", text: "Mình muốn tìm tai nghe không dây dưới 3 triệu." }, { label: "Quà tặng dưới 500k", text: "Mình muốn tìm quà tặng dưới 500 nghìn." }, { label: "So sánh sản phẩm", text: "Hãy giúp mình so sánh các sản phẩm phù hợp." }];

  return <section id={compact ? "floating-chat" : "inline-chat"} aria-label={`Synee AI — ${compact ? "trò chuyện thu gọn" : "trợ lý mua sắm"}`} className={`chat-panel ${compact ? "compact" : ""} ${c.audioFile ? "has-audio" : ""}`}>
    <div className="chat-header">
      <div className="mode-toggle" role="group" aria-label="Chế độ trò chuyện">
        <button type="button" aria-pressed={!voicePreview} className={!voicePreview ? "selected" : ""} onClick={() => onModeChange(false)}>Chat</button>
        <button type="button" aria-pressed={voicePreview} className={voicePreview ? "selected" : ""} onClick={() => onModeChange(true)}>Voice</button>
      </div>
      {voicePreview && <span className="voice-preview" role="status">Voice · Bản xem trước</span>}
      {compact && <button className="icon-button close-chat" aria-label="Đóng trò chuyện" onClick={onClose}><Asset name="close" /></button>}
    </div>
    <div className="chat-body">
      <div className="conversation-history" ref={historyRef} role="log" aria-label="Nội dung trò chuyện" aria-live="polite" aria-relevant="additions text" tabIndex={0}>
        {c.messages.map((message, index) => <div className={`message ${message.role}`} key={index}>
          {message.role === "agent" && <span className="synee-avatar" aria-label="Synee AI"><Asset name={compact ? "compactSparkle" : "sparkle"} /></span>}
          <p className="message-bubble">{message.text}</p>
        </div>)}
        {c.isLoading && <div className="message agent"><span className="synee-avatar"><Asset name={compact ? "compactSparkle" : "sparkle"} /></span><span className="typing" aria-label="Synee AI đang xử lý"><i /><i /><i /></span></div>}
      </div>
      <div id={statusId} className="chat-status" aria-live="polite">
        {c.errorMessage ? <p role="alert" className="error">{c.errorMessage}</p>
          : c.cooldownSeconds > 0 ? <p role="status">Dịch vụ hội thoại đang tạm giới hạn. Có thể gửi tiếp sau {c.cooldownSeconds} giây.</p>
          : c.isLoading ? <p role="status">{c.audioFile ? "Đang nhận dạng ghi âm và chờ phản hồi…" : "Đang chờ phản hồi…"}</p>
          : !c.backendReady ? <p role="status">Đang chờ kết nối backend sẵn sàng. Hệ thống sẽ tự kiểm tra lại…</p>
          : null}
      </div>
      <div className="suggestions" aria-label="Gợi ý trò chuyện">
        {prompts.map(p => <button key={p.label} className="suggestion" disabled={c.isLoading || !!c.audioFile} onClick={() => { c.setInput(p.text); inputRef.current?.focus(); }}>{p.label}</button>)}
      </div>
      <form className="composer" onSubmit={e => { e.preventDefault(); void c.sendMessage(); }}>
        <label className="sr-only" htmlFor={`${prefix}-message`}>Tin nhắn cho Synee AI</label>
        <textarea id={`${prefix}-message`} ref={inputRef} rows={1} value={c.input} onChange={e => c.setInput(e.target.value)} disabled={c.isLoading || !!c.audioFile} placeholder={c.audioFile ? "Đã chọn ghi âm cho lượt thoại này" : "Bạn đang tìm gì hôm nay?"} aria-describedby={statusId}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void c.sendMessage(); } }} />
        {c.audioFile && <div className="audio-preview">
          <div><span>{c.audioFile.name}</span><button type="button" disabled={c.isLoading} onClick={c.clearAudio}>Bỏ ghi âm</button></div>
          {c.audioPreviewUrl && <audio controls preload="metadata" src={c.audioPreviewUrl} aria-label="Nghe lại ghi âm" />}
        </div>}
        <div className="composer-actions">
          <input ref={fileRef} className="sr-only" tabIndex={-1} type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.webm,audio/*" aria-label="Chọn file ghi âm" disabled={c.isLoading} onChange={e => { const file = e.target.files?.[0]; if (file) c.selectAudio(file); e.target.value = ""; }} />
          <button className="icon-button upload-button" type="button" aria-label="Tải file ghi âm MP3 hoặc âm thanh" title="WAV, MP3, M4A, FLAC, OGG, WebM · tối đa 25 MB / 120 giây" disabled={c.isLoading} onClick={() => fileRef.current?.click()}><Asset name={compact ? "compactAttach" : "attach"} /></button>
          {c.audioFile && <span className="upload-limit">Tối đa 25 MB / 120 giây</span>}
          <button className={`press-button ${c.isLoading ? "is-loading" : ""} ${c.audioFile ? "has-upload" : ""} ${c.errorMessage ? "is-error" : ""}`} type="submit" disabled={disabled} aria-describedby={statusId}>
            <span className="button-rear" /><span className="button-face"><Asset name={compact ? "compactSend" : "send"} />{c.isLoading ? "Đang tìm…" : c.errorMessage ? "Thử lại" : c.audioFile ? "Gửi ghi âm" : "Gửi"}</span>
          </button>
        </div>
      </form>
      <p className="resume-prompt">Đã từng trò chuyện? <button onClick={onAccount} className="text-link">Đăng nhập</button> để tiếp tục cuộc hội thoại.</p>
    </div>
  </section>;
}
