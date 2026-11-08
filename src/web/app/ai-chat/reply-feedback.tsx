"use client";

import { createContext, useContext, useId, useRef, useState, type ReactNode } from "react";
import type { Message } from "@/utils/use-conversation";
import { conversationApi, type StoredFeedback } from "@/utils/conversation-api";
import { useSharedConversation } from "../components/conversation-provider";
import { Icon } from "./icons";

type Rating = "positive" | "negative" | null;
type Feedback = { rating: Rating; comment: string; draft: string; open: boolean; error: string; notice: string };
const emptyFeedback: Feedback = { rating: null, comment: "", draft: "", open: false, error: "", notice: "" };
type FeedbackContextValue = {
  entries: ReadonlyMap<string, Feedback>;
  update: (key: string, change: (previous: Feedback) => Feedback, initial: Feedback) => void;
};
const FeedbackContext = createContext<FeedbackContextValue | null>(null);

/** Drafts stay local; saved entries are keyed by the database message ID. */
export function ReplyFeedbackProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<ReadonlyMap<string, Feedback>>(() => new Map());
  const update: FeedbackContextValue["update"] = (key, change, initial) => {
    setEntries(previous => {
      const next = new Map(previous);
      next.set(key, change(previous.get(key) ?? initial));
      return next;
    });
  };
  return <FeedbackContext.Provider value={{ entries, update }}>{children}</FeedbackContext.Provider>;
}

export function ReplyFeedback({ message, messageNumber, onCopy, disabled }: { message: Message; messageNumber: number; onCopy: () => void; disabled: boolean }) {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error("ReplyFeedbackProvider is required");
  const c = useSharedConversation();
  const { entries, update: updateEntry } = context;
  const key = message.id ?? `local-${messageNumber}`;
  const initial = { ...emptyFeedback, ...message.feedback, draft: message.feedback?.comment ?? "" };
  const feedback = entries.get(key) ?? initial;
  const update = (_message: Message, change: (previous: Feedback) => Feedback) => updateEntry(key, change, initial);
  const [pending, setPending] = useState(false);
  const saveLock = useRef(false);
  const cannotSave = disabled || pending || !message.id;
  const id = useId();
  const textButtonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const suffix = `cho câu trả lời ${messageNumber}`;
  const close = () => {
    update(message, previous => ({ ...previous, open: false, error: "" }));
    requestAnimationFrame(() => textButtonRef.current?.focus({ preventScroll: true }));
  };
  const save = async (value: StoredFeedback, closeForm = false) => {
    if (!message.id || saveLock.current || disabled) return;
    saveLock.current = true; setPending(true);
    update(message, previous => ({ ...previous, error: "", notice: "Đang lưu…" }));
    try {
      if (value.rating === null && !value.comment) await conversationApi.deleteFeedback(message.id);
      else await conversationApi.putFeedback(message.id, value);
      c.setMessageFeedback(message.id, value);
      update(message, previous => ({ ...previous, ...value, draft: closeForm ? value.comment : previous.draft,
        open: closeForm ? false : previous.open, error: "", notice: "Đã lưu góp ý." }));
      if (closeForm) requestAnimationFrame(() => textButtonRef.current?.focus({ preventScroll: true }));
    } catch (error) {
      update(message, previous => ({ ...previous, notice: "", error: error instanceof Error ? error.message : "Chưa lưu được. Hãy thử lại." }));
    } finally { saveLock.current = false; setPending(false); }
  };
  const rate = (rating: Exclude<Rating, null>) => void save({ rating: feedback.rating === rating ? null : rating, comment: feedback.comment });

  return <div className="ai-reply-feedback" aria-live="off" onKeyDown={event => {
    if (feedback.open && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
  }}>
    <div className="ai-message-tools" role="group" aria-label={`Thao tác ${suffix}`}>
      <button type="button" aria-label={`Sao chép tin nhắn ${messageNumber}`} title="Sao chép" onClick={onCopy} disabled={disabled}><Icon name="copy" /></button>
      <button type="button" className="ai-feedback-positive" aria-label={`Phản hồi tích cực ${suffix}`} title={!message.id ? "Đăng nhập và gửi tin nhắn để lưu đánh giá" : feedback.rating === "positive" ? "Bỏ đánh giá tích cực" : "Phản hồi tích cực"} aria-pressed={feedback.rating === "positive"} onClick={() => rate("positive")} disabled={cannotSave}><Icon name="like" /></button>
      <button type="button" className="ai-feedback-negative" aria-label={`Phản hồi tiêu cực ${suffix}`} title={!message.id ? "Đăng nhập và gửi tin nhắn để lưu đánh giá" : feedback.rating === "negative" ? "Bỏ đánh giá tiêu cực" : "Phản hồi tiêu cực"} aria-pressed={feedback.rating === "negative"} onClick={() => rate("negative")} disabled={cannotSave}><Icon name="dislike" /></button>
      <button ref={textButtonRef} type="button" className="ai-feedback-text" aria-label={`Góp ý bằng văn bản ${suffix}`} title={feedback.comment ? "Chỉnh sửa góp ý" : "Góp ý bằng văn bản"} aria-pressed={!!feedback.comment} aria-expanded={feedback.open} aria-controls={`${id}-form`} onClick={() => {
        if (feedback.open) { close(); return; }
        update(message, previous => ({ ...previous, open: true, error: "" }));
        requestAnimationFrame(() => inputRef.current?.focus());
      }} disabled={cannotSave}><Icon name="message" /></button>
    </div>
    <p className="ai-reply-feedback-status" role="status" aria-live="polite">{feedback.notice}</p>
    {!message.id && messageNumber > 1 && <p className="ai-reply-feedback-status">Đăng nhập để lưu đánh giá cho câu trả lời.</p>}
    {!feedback.open && feedback.error && <p className="ai-reply-feedback-error" role="alert">{feedback.error}</p>}
    {feedback.open && <form id={`${id}-form`} className="ai-reply-feedback-form" aria-label={`Góp ý ${suffix}`} noValidate onSubmit={event => {
      event.preventDefault();
      const comment = feedback.draft.trim();
      if (!comment && !feedback.comment) {
        update(message, previous => ({ ...previous, error: "Nhập nội dung góp ý trước khi gửi." }));
        inputRef.current?.focus();
        return;
      }
      void save({ rating: feedback.rating, comment }, true);
    }}>
      <div className="ai-reply-feedback-heading"><label htmlFor={`${id}-text`}>Góp ý cho câu trả lời này</label></div>
      <p id={`${id}-note`}>Góp ý được lưu trong tài khoản của bạn.</p>
      <textarea ref={inputRef} id={`${id}-text`} value={feedback.draft} disabled={pending} maxLength={1000} rows={3} placeholder="Bạn muốn Synee cải thiện điều gì?" aria-invalid={!!feedback.error} aria-describedby={`${id}-note ${id}-count${feedback.error ? ` ${id}-error` : ""}`} onChange={event => {
        const draft = event.target.value;
        update(message, previous => ({ ...previous, draft, error: "" }));
      }} />
      <p id={`${id}-count`} className="ai-reply-feedback-count">{feedback.draft.length}/1.000 ký tự</p>
      {feedback.error && <p id={`${id}-error`} className="ai-reply-feedback-error" role="alert">{feedback.error}</p>}
      <div className="ai-reply-feedback-actions"><button type="button" disabled={pending} onClick={close}>Hủy</button><button type="submit" disabled={cannotSave}>{pending ? "Đang lưu…" : "Gửi góp ý"} <Icon name="arrowUp" /></button></div>
    </form>}
  </div>;
}
