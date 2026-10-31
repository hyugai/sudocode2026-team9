"use client";

import { useEffect, useRef, useState } from "react";
import { ChatApiError, createChatClient, type DebugInfo } from "./chat-api";
import { conversationStorageKey, readGuestSession, writeGuestSession } from "./conversation-session";

// Keep the legacy deployment contract. This public URL must never contain a key.
export const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || (
  process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://sudo-code-2026-group-9.onrender.com"
)).replace(/\/$/, "");

export interface Message { role: "user" | "agent"; text: string }
export interface LogEntry { userMessage: string; debug: DebugInfo }
export interface Consultation { sku: string; name: string; price: string; quantity: number }
const welcome: Message[] = [{ role: "agent", text: "Mình là Synee AI. Mình có thể giúp bạn tìm sản phẩm phù hợp với nhu cầu và ngân sách." }];

/** One owner for both presentations: switching visibility never starts a turn. */
export function useConversation() {
  const [messages, setMessages] = useState<Message[]>(welcome);
  const [debugLogs, setDebugLogs] = useState<LogEntry[]>([]);
  const [input, setInput] = useState("");
  const [customerPhone, updateCustomerPhone] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreviewUrl, setAudioPreviewUrl] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [backendReady, setBackendReady] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [sessionId, setSessionId] = useState("");
  const [voicePreview, setVoicePreview] = useState(false);
  const [voiceActive, setVoiceActive] = useState(false);
  const [consultation, setConsultation] = useState<Consultation | null>(null);
  const conversationIdRef = useRef("");
  const [chatClient] = useState(() => createChatClient(apiBase));
  const [sessionReady, setSessionReady] = useState(false);
  const [sessionNotice, setSessionNotice] = useState("");
  const [isClearing, setIsClearing] = useState(false);

  useEffect(() => {
    try {
      const saved = readGuestSession(sessionStorage.getItem(conversationStorageKey));
      if (saved) {
        // Browser-only state must hydrate after the server's initial render.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setMessages(saved.messages.length ? saved.messages : welcome);
        setInput(saved.input); updateCustomerPhone(saved.customerPhone); setVoicePreview(saved.voicePreview);
        setConsultation(saved.consultation); setSessionId(saved.sessionId); conversationIdRef.current = saved.sessionId;
      }
    } catch { setSessionNotice("Không khôi phục được hội thoại đã lưu. Bạn đang dùng phiên khách mới."); }
    setSessionReady(true);
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    try { sessionStorage.setItem(conversationStorageKey, writeGuestSession({ messages, sessionId, input, customerPhone, voicePreview, consultation })); }
    catch {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSessionNotice("Trình duyệt chưa lưu được hội thoại. Hãy giữ tab mở để tiếp tục tư vấn.");
    }
  }, [sessionReady, messages, sessionId, input, customerPhone, voicePreview, consultation]);

  const resetConversation = () => {
    setMessages(welcome); setDebugLogs([]); setInput(""); setAudioFile(null); setAudioPreviewUrl("");
    setSessionId(""); conversationIdRef.current = ""; setConsultation(null); setErrorMessage(""); setSessionNotice("");
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
      return;
    }
    setAudioFile(file);
    // The URL belongs to the shared file, not either mounted chat surface.
    setAudioPreviewUrl(URL.createObjectURL(file));
  };

  const sendMessage = async () => {
    if (!sessionReady || isClearing || voiceActive || (!input.trim() && !audioFile) || chatClient.isSending || !backendReady || chatClient.retryAfterSeconds) return;
    const userMessage = input.trim();
    const selectedAudio = audioFile;
    const conversationId = conversationIdRef.current || crypto.randomUUID();
    conversationIdRef.current = conversationId;
    setSessionId(conversationId);
    setIsLoading(true);
    setErrorMessage("");
    try {
      const contextualMessage = consultation && !selectedAudio
        ? `Ngữ cảnh tư vấn: ${consultation.name} (${consultation.sku}), giá tham chiếu ${consultation.price}, số lượng ${consultation.quantity}.\nCâu hỏi của khách: ${userMessage}`
        : userMessage;
      const data = await chatClient.send({ conversationId, message: contextualMessage, audioFile: selectedAudio, customerPhone });
      if (!data) return;
      setCooldownSeconds(chatClient.retryAfterSeconds);
      const transcript = selectedAudio ? data.transcript : (data.normalized_message ?? userMessage);
      if (typeof transcript !== "string" || !transcript.trim()) {
        throw new Error("Không nhận được văn bản từ ghi âm. Vui lòng thử lại.");
      }
      setMessages(prev => [...prev,
        { role: "user", text: transcript },
        { role: "agent", text: data.response || "Chưa nhận được phản hồi từ tư vấn viên." },
      ]);
      if (selectedAudio) clearAudio();
      else setInput("");
      if (data.debug) setDebugLogs(prev => [...prev, { userMessage: transcript, debug: data.debug! }]);
    } catch (error) {
      if (error instanceof ChatApiError && error.connectionLost) setBackendReady(false);
      if (error instanceof ChatApiError) setCooldownSeconds(error.retryAfterSeconds);
      setErrorMessage(error instanceof ChatApiError && error.retryAfterSeconds > 0
        ? ""
        : error instanceof Error ? error.message : "Lỗi kết nối. Vui lòng thử lại.");
    } finally { setIsLoading(false); }
  };

  return { messages, debugLogs, input, setInput, customerPhone, setCustomerPhone, isLoading: isLoading || isClearing || voiceActive,
    audioFile, audioPreviewUrl, clearAudio, selectAudio, errorMessage, backendReady,
    cooldownSeconds, sessionId, sendMessage, voicePreview, setVoicePreview, consultation, setConsultation,
    sessionReady, sessionNotice, endConversation, voiceActive, setVoiceActive };
}

export type Conversation = ReturnType<typeof useConversation>;
