"use client";

import { createContext, useContext, useId, useRef, useState, type ReactNode } from "react";
import type { Message } from "@/utils/use-conversation";
import { Icon } from "./icons";

type Rating = "positive" | "negative" | null;
type Feedback = { rating: Rating; comment: string; draft: string; open: boolean; error: string; notice: string };
const emptyFeedback: Feedback = { rating: null, comment: "", draft: "", open: false, error: "", notice: "" };
type FeedbackContextValue = {
  entries: ReadonlyMap<Message, Feedback>;
  update: (message: Message, change: (previous: Feedback) => Feedback) => void;
};
const FeedbackContext = createContext<FeedbackContextValue | null>(null);

/** Ephemeral, per-reply state survives filtering while this Chat view is mounted. */
export function ReplyFeedbackProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<ReadonlyMap<Message, Feedback>>(() => new Map());
  const update: FeedbackContextValue["update"] = (message, change) => {
    setEntries(previous => {
      const next = new Map(previous);
      next.set(message, change(previous.get(message) ?? emptyFeedback));
      return next;
    });
  };
  return <FeedbackContext.Provider value={{ entries, update }}>{children}</FeedbackContext.Provider>;
}

export function ReplyFeedback({ message, messageNumber, onCopy, disabled }: { message: Message; messageNumber: number; onCopy: () => void; disabled: boolean }) {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error("ReplyFeedbackProvider is required");
  const { entries, update } = context;
  const feedback = entries.get(message) ?? emptyFeedback;
  const id = useId();
  const textButtonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const suffix = `cho câu trả lời ${messageNumber}`;
  const close = () => {
    update(message, previous => ({ ...previous, open: false, error: "" }));
    requestAnimationFrame(() => textButtonRef.current?.focus({ preventScroll: true }));
  };
  const rate = (rating: Exclude<Rating, null>) => {
    update(message, previous => ({ ...previous,
      rating: previous.rating === rating ? null : rating,
      notice: previous.rating === rating ? "Đã bỏ đánh giá (demo)." : `Đã ghi nhận đánh giá ${rating === "positive" ? "tích cực" : "tiêu cực"} (demo).`,
    }));
  };

  return <div className="ai-reply-feedback" aria-live="off" onKeyDown={event => {
    if (feedback.open && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
  }}>
    <div className="ai-message-tools" role="group" aria-label={`Thao tác ${suffix}`}>
      <button type="button" aria-label={`Sao chép tin nhắn ${messageNumber}`} title="Sao chép" onClick={onCopy} disabled={disabled}><Icon name="copy" /></button>
      <button type="button" className="ai-feedback-positive" aria-label={`Phản hồi tích cực ${suffix}`} title={feedback.rating === "positive" ? "Bỏ đánh giá tích cực" : "Phản hồi tích cực"} aria-pressed={feedback.rating === "positive"} onClick={() => rate("positive")} disabled={disabled}><Icon name="like" /></button>
      <button type="button" className="ai-feedback-negative" aria-label={`Phản hồi tiêu cực ${suffix}`} title={feedback.rating === "negative" ? "Bỏ đánh giá tiêu cực" : "Phản hồi tiêu cực"} aria-pressed={feedback.rating === "negative"} onClick={() => rate("negative")} disabled={disabled}><Icon name="dislike" /></button>
      <button ref={textButtonRef} type="button" className="ai-feedback-text" aria-label={`Góp ý bằng văn bản ${suffix}`} title={feedback.comment ? "Chỉnh sửa góp ý" : "Góp ý bằng văn bản"} aria-pressed={!!feedback.comment} aria-expanded={feedback.open} aria-controls={`${id}-form`} onClick={() => {
        if (feedback.open) { close(); return; }
        update(message, previous => ({ ...previous, open: true, error: "" }));
        requestAnimationFrame(() => inputRef.current?.focus());
      }} disabled={disabled}><Icon name="message" /></button>
    </div>
    <p className="ai-reply-feedback-status" role="status" aria-live="polite">{feedback.notice}</p>
    {feedback.open && <form id={`${id}-form`} className="ai-reply-feedback-form" aria-label={`Góp ý ${suffix}`} noValidate onSubmit={event => {
      event.preventDefault();
      const comment = feedback.draft.trim();
      if (!comment) {
        update(message, previous => ({ ...previous, error: "Nhập nội dung góp ý trước khi gửi." }));
        inputRef.current?.focus();
        return;
      }
      // Demo only: keep feedback in component memory; never send or persist it.
      update(message, previous => ({ ...previous, comment, draft: comment, open: false, error: "", notice: "Đã ghi nhận góp ý bằng văn bản (demo)." }));
      requestAnimationFrame(() => textButtonRef.current?.focus({ preventScroll: true }));
    }}>
      <div className="ai-reply-feedback-heading"><label htmlFor={`${id}-text`}>Góp ý cho câu trả lời này</label><span>Demo</span></div>
      <p id={`${id}-note`}>Nội dung chỉ được giữ tạm trong giao diện, chưa gửi lên hệ thống.</p>
      <textarea ref={inputRef} id={`${id}-text`} value={feedback.draft} maxLength={1000} rows={3} placeholder="Bạn muốn Synee cải thiện điều gì?" aria-invalid={!!feedback.error} aria-describedby={`${id}-note ${id}-count${feedback.error ? ` ${id}-error` : ""}`} onChange={event => {
        const draft = event.target.value;
        update(message, previous => ({ ...previous, draft, error: "" }));
      }} />
      <p id={`${id}-count`} className="ai-reply-feedback-count">{feedback.draft.length}/1.000 ký tự</p>
      {feedback.error && <p id={`${id}-error`} className="ai-reply-feedback-error" role="alert">{feedback.error}</p>}
      <div className="ai-reply-feedback-actions"><button type="button" onClick={close}>Hủy</button><button type="submit">Gửi góp ý <Icon name="arrowUp" /></button></div>
    </form>}
  </div>;
}
