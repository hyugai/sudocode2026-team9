"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatApiError, chatStageLabels, createChatClient, type ChatStage, type DebugInfo } from "./chat-api";
import { conversationStorageKey, readGuestSession, writeGuestSession } from "./conversation-session";
import { readCallBrief, type CallBrief } from "./call-brief";
import { accountConversationKey, conversationApi, type SavedConversation, type StoredFeedback } from "./conversation-api";
import type { LiveProductDetails } from "./catalog";
import { loadChatCatalog } from "./chat-products";

// Keep the legacy deployment contract. This public URL must never contain a key.
export const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || (
  process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://telesale-agent-api-3no2.onrender.com"
)).replace(/\/$/, "");

export interface Message { id?: string; role: "user" | "agent"; text: string; feedback?: StoredFeedback | null }
export interface LogEntry { userMessage: string; debug: DebugInfo }
export interface Consultation { sku: string; name: string; price: string; quantity: number }
const welcome: Message[] = [{ role: "agent", text: "Mình là Synee AI. Mình có thể giúp bạn tìm sản phẩm phù hợp với nhu cầu và ngân sách." }];

/** One owner for both presentations: switching visibility never starts a turn. */
export function useConversation(persistGuest = true, enabled = true) {
  const accountMode = !persistGuest && enabled;
  const [messages, setMessages] = useState<Message[]>(welcome);
  const [debugLogs, setDebugLogs] = useState<LogEntry[]>([]);
  const [callBrief, setCallBrief] = useState<CallBrief | null>(null);
  const [callBriefStale, setCallBriefStale] = useState(false);
  const [input, setInput] = useState("");
  const [customerPhone, updateCustomerPhone] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [pendingMessage, setPendingMessage] = useState("");
  const [processingStage, setProcessingStage] = useState<ChatStage | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreviewUrl, setAudioPreviewUrl] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [backendReady, setBackendReady] = useState(false);
  const [chatCatalog, setChatCatalog] = useState<LiveProductDetails[]>([]);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [sessionId, setSessionId] = useState("");
  const [voicePreview, setVoicePreview] = useState(false);
  const [voiceActive, setVoiceActive] = useState(false);
  const [consultation, setConsultation] = useState<Consultation | null>(null);
  const conversationIdRef = useRef("");
  const [chatClient] = useState(() => createChatClient(apiBase, fetch, Date.now, accountMode));
  const [sessionReady, setSessionReady] = useState(false);
  const [sessionNotice, setSessionNotice] = useState("");
  const [isClearing, setIsClearing] = useState(false);
  const [conversationEnded, setConversationEnded] = useState(false);
  const submissionLock = useRef(false);
  const applySaved = useCallback((saved: SavedConversation) => {
    setMessages(saved.messages.length ? saved.messages.map(message => ({
      id: message.id, role: message.role, text: message.content, feedback: message.feedback,
    })) : welcome);
    setSessionId(saved.id); conversationIdRef.current = saved.id;
    setCallBrief(readCallBrief(saved.call_brief)); setCallBriefStale(false);
    updateCustomerPhone(saved.customer_phone ?? "");
    setConversationEnded(saved.status === "ended");
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const restore = async () => {
      try {
        if (accountMode) {
          const id = sessionStorage.getItem(accountConversationKey);
          if (id) {
            const saved = await conversationApi.load(id);
            if (active) applySaved(saved);
          }
          return;
        }
        const saved = persistGuest ? readGuestSession(sessionStorage.getItem(conversationStorageKey)) : null;
        if (saved) {
          // Browser-only state must hydrate after the server's initial render.
          setMessages(saved.messages.length ? saved.messages : welcome);
          setInput(saved.input); updateCustomerPhone(saved.customerPhone); setVoicePreview(saved.voicePreview);
          setConsultation(saved.consultation); setSessionId(saved.sessionId); conversationIdRef.current = saved.sessionId;
          setCallBrief(readCallBrief(saved.callBrief));
        }
      } catch { if (active) setSessionNotice("Chưa khôi phục được hội thoại. Bạn có thể thử mở lại từ lịch sử."); }
      finally { if (active) setSessionReady(true); }
    };
    void restore();
    return () => { active = false; };
  }, [persistGuest, enabled, accountMode, applySaved]);

  useEffect(() => {
    if (!sessionReady || !persistGuest) return;
    try { sessionStorage.setItem(conversationStorageKey, writeGuestSession({ messages, sessionId, input, customerPhone, voicePreview, consultation, callBrief })); }
    catch {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSessionNotice("Trình duyệt chưa lưu được hội thoại. Hãy giữ tab mở để tiếp tục tư vấn.");
    }
  }, [persistGuest, sessionReady, messages, sessionId, input, customerPhone, voicePreview, consultation, callBrief]);

  const resetConversation = () => {
    setMessages(welcome); setDebugLogs([]); setCallBrief(null); setCallBriefStale(false); setInput(""); setAudioFile(null); setAudioPreviewUrl("");
    setSessionId(""); conversationIdRef.current = ""; setConsultation(null); setErrorMessage(""); setSessionNotice("");
    setConversationEnded(false);
    if (accountMode) {
      try { sessionStorage.removeItem(accountConversationKey); }
      catch { setSessionNotice("Trình duyệt chưa xóa được dấu hội thoại cũ."); }
    }
  };
  const rememberConversation = (id: string) => {
    try { sessionStorage.setItem(accountConversationKey, id); }
    catch { setSessionNotice("Hội thoại vẫn lưu trong tài khoản; trình duyệt chưa ghi nhớ lần mở gần nhất."); }
  };
  const openConversation = async (id: string) => {
    if (!accountMode || submissionLock.current || isLoading || isClearing || voiceActive) throw new Error("Chờ xử lý hoàn tất trước khi mở hội thoại.");
    submissionLock.current = true; setIsClearing(true);
    try {
      const saved = await conversationApi.load(id);
      resetConversation(); applySaved(saved); rememberConversation(id);
    } finally { submissionLock.current = false; setIsClearing(false); }
  };
  const setCustomerPhone = (phone: string) => {
    if (isLoading || isClearing || voiceActive) return;
    const next = phone.trim();
    if (next !== customerPhone) { resetConversation(); updateCustomerPhone(next); }
  };
  const endConversation = async () => {
    if (isLoading || isClearing || voiceActive) return;
    setIsClearing(true);
    try { await chatClient.clearSession(conversationIdRef.current); resetConversation(); }
    finally { setIsClearing(false); }
  };

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      const ready = await chatClient.isReady(AbortSignal.any([
        controller.signal, AbortSignal.timeout(5000),
      ]));
      if (controller.signal.aborted) return;
      setBackendReady(ready);
      timer = setTimeout(check, ready ? 5000 : 2000);
    };
    void check();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [chatClient]);

  useEffect(() => {
    if (!enabled || !backendReady) return;
    const controller = new AbortController();
    void loadChatCatalog(fetch, AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]))
      .then(products => { if (!controller.signal.aborted) setChatCatalog(products); })
      .catch(() => {}); // Catalog failure must not interrupt the text conversation.
    return () => controller.abort();
  }, [enabled, backendReady]);

  useEffect(() => {
    if (!cooldownSeconds) return;
    const timer = setTimeout(() => setCooldownSeconds(chatClient.retryAfterSeconds), 1000);
    return () => clearTimeout(timer);
  }, [chatClient, cooldownSeconds]);

  useEffect(() => () => {
    if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
  }, [audioPreviewUrl]);

  const clearAudio = () => { setAudioFile(null); setAudioPreviewUrl(""); };

  const selectAudio = (file: File) => {
    setErrorMessage("");
    if (!file.size || file.size > 25 * 1024 * 1024) {
      setErrorMessage("Hãy chọn file ghi âm có dung lượng từ 1 byte đến 25 MB.");
      clearAudio();
      return false;
    }
    setAudioFile(file);
    // The URL belongs to the shared file, not either mounted chat surface.
    setAudioPreviewUrl(URL.createObjectURL(file));
    return true;
  };

  const sendMessage = async () => {
    if (!sessionReady || conversationEnded || submissionLock.current || isClearing || voiceActive || (!input.trim() && !audioFile) || chatClient.isSending || !backendReady || chatClient.retryAfterSeconds) return;
    const userMessage = input.trim();
    const selectedAudio = audioFile;
    submissionLock.current = true;
    setIsLoading(true);
    setStreamingText("");
    setProcessingStage("processing");
    setPendingMessage(selectedAudio ? "Đang nhận dạng ghi âm…" : userMessage);
    setErrorMessage("");
    try {
      const conversationId = conversationIdRef.current || (accountMode ? (await conversationApi.create(customerPhone)).id : crypto.randomUUID());
      conversationIdRef.current = conversationId; setSessionId(conversationId);
      if (accountMode) rememberConversation(conversationId);
      const contextualMessage = consultation && !selectedAudio
        ? `Ngữ cảnh tư vấn: ${consultation.name} (${consultation.sku}), giá tham chiếu ${consultation.price}, số lượng ${consultation.quantity}.\nCâu hỏi của khách: ${userMessage}`
        : userMessage;
      const data = await chatClient.send({ conversationId, message: contextualMessage, audioFile: selectedAudio, customerPhone }, setStreamingText, setProcessingStage);
      if (!data) return;
      setCooldownSeconds(chatClient.retryAfterSeconds);
      const transcript = selectedAudio ? data.transcript : (data.normalized_message ?? userMessage);
      if (typeof transcript !== "string" || !transcript.trim()) {
        throw new Error("Không nhận được văn bản từ ghi âm. Vui lòng thử lại.");
      }
      setMessages(prev => [...prev,
        { id: data.user_message_id, role: "user", text: transcript },
        { id: data.message_id, role: "agent", text: data.response || "Chưa nhận được phản hồi từ tư vấn viên.", feedback: null },
      ]);
      setCallBrief(data.callBrief);
      setCallBriefStale(false);
      if (selectedAudio) clearAudio();
      else setInput("");
      if (data.debug) setDebugLogs(prev => [...prev, { userMessage: transcript, debug: data.debug! }]);
    } catch (error) {
      setCallBriefStale(true);
      if (error instanceof ChatApiError && error.connectionLost) setBackendReady(false);
      if (error instanceof ChatApiError) setCooldownSeconds(error.retryAfterSeconds);
      setErrorMessage(error instanceof ChatApiError && error.retryAfterSeconds > 0
        ? ""
        : error instanceof Error ? error.message : "Lỗi kết nối. Vui lòng thử lại.");
    } finally { submissionLock.current = false; setIsLoading(false); setStreamingText(""); setPendingMessage(""); setProcessingStage(null); }
  };

  const setMessageFeedback = (id: string, feedback: StoredFeedback | null) => {
    setMessages(previous => previous.map(message => message.id === id ? { ...message, feedback } : message));
  };

  return { messages, debugLogs, callBrief, callBriefStale, input, setInput, customerPhone, setCustomerPhone, isLoading: isLoading || isClearing || voiceActive,
    audioFile, audioPreviewUrl, clearAudio, selectAudio, errorMessage, backendReady,
    cooldownSeconds, sessionId, sendMessage, voicePreview, setVoicePreview, consultation, setConsultation,
    sessionReady, sessionNotice, endConversation, voiceActive, setVoiceActive,
    accountMode, conversationEnded, openConversation, setMessageFeedback, streamingText, pendingMessage, chatCatalog,
    processingLabel: processingStage ? chatStageLabels[processingStage] : "" };
}

export type Conversation = ReturnType<typeof useConversation>;
