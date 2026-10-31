export interface DebugInfo {
  intent: string;
  retrieved_knowledge: unknown[];
  steps?: { action: string; rationale: string; tool: string | null; tool_args: unknown }[];
}

interface ChatResponse {
  response: string;
  transcript?: string;
  normalized_message?: string;
  debug?: DebugInfo;
  retry_after_seconds?: number;
  latency?: Record<string, unknown>;
}

export interface ChatStreamEvent {
  type: "input" | "delta" | "replace" | "response_complete";
  text?: string;
  transcript?: string;
  normalized_message?: string;
}

interface ChatTurn {
  conversationId: string;
  message: string;
  audioFile: File | null;
  customerPhone: string;
}

export class ChatApiError extends Error {
  readonly connectionLost: boolean;
  readonly retryAfterSeconds: number;

  constructor(message: string, connectionLost = false, retryAfterSeconds = 0) {
    super(message);
    this.connectionLost = connectionLost;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function createChatClient(apiBase: string, fetcher: typeof fetch = fetch, now = Date.now) {
  let sending = false;
  let retryAt = 0;
  const remaining = () => Math.max(0, Math.ceil((retryAt - now()) / 1000));
  const defer = (seconds: number) => {
    if (Number.isFinite(seconds) && seconds > 0) retryAt = Math.max(retryAt, now() + seconds * 1000);
  };

  return {
    get isSending() { return sending; },
    get retryAfterSeconds() { return remaining(); },

    async isReady(signal: AbortSignal): Promise<boolean> {
      try {
        const response = await fetcher(`${apiBase}/health`, { signal, cache: "no-store" });
        return response.ok;
      } catch {
        return false;
      }
    },

    async clearSession(conversationId: string): Promise<void> {
      if (sending) throw new ChatApiError("Chờ Synee trả lời trước khi kết thúc hội thoại.");
      if (!conversationId) return;
      try {
        const response = await fetcher(`${apiBase}/api/sessions/${encodeURIComponent(conversationId)}`, {
          method: "DELETE", signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) throw new ChatApiError(response.status === 401 || response.status === 403
          ? "Dịch vụ chưa cấp quyền kết thúc hội thoại. Dữ liệu trên thiết bị vẫn được giữ."
          : "Chưa kết thúc được hội thoại. Hãy thử lại; dữ liệu vẫn được giữ.");
        const data = await response.json();
        if (data?.status !== "cleared" || data.conversation_id !== conversationId) throw new ChatApiError("Dịch vụ chưa xác nhận kết thúc đúng hội thoại. Dữ liệu vẫn được giữ.");
      } catch (e) {
        if (e instanceof ChatApiError) throw e;
        throw new ChatApiError("Không kết nối được dịch vụ để kết thúc hội thoại. Dữ liệu vẫn được giữ.", true);
      }
    },

    async send(turn: ChatTurn): Promise<ChatResponse | null> {
      // Set synchronously, before the first await, to reject rapid duplicate submits.
      if (sending) return null;
      if (remaining()) throw new ChatApiError("Vui lòng chờ hết thời gian giới hạn trước khi gửi lại.", false, remaining());
      sending = true;
      try {
        let body: BodyInit;
        let headers: HeadersInit | undefined;
        if (turn.audioFile) {
          const form = new FormData();
          form.append("conversation_id", turn.conversationId);
          form.append("file", turn.audioFile);
          form.append("stream", "true");
          if (turn.customerPhone) form.append("customer_phone", turn.customerPhone);
          body = form;
        } else {
          headers = { "Content-Type": "application/json" };
          body = JSON.stringify({
            conversation_id: turn.conversationId,
            message: turn.message,
            customer_phone: turn.customerPhone || null,
            stream: true,
          });
        }

        let response: Response;
        try {
          response = await fetcher(`${apiBase}/api/chat${turn.audioFile ? "/audio" : ""}`, {
            method: "POST", headers, body,
          });
        } catch {
          // A lost response does not prove that the backend skipped the turn.
          // Never automatically retry a POST that may have performed agent actions.
          throw new ChatApiError("Mất kết nối với backend. File và nội dung vẫn được giữ lại; hãy chờ kết nối sẵn sàng rồi thử lại.", true);
        }

        if (response.ok && response.headers.get("Content-Type")?.includes("text/event-stream")) {
          if (!response.body) throw new ChatApiError("Không nhận được luồng phản hồi.", true);
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          try {
            while (true) {
              const { value, done } = await reader.read();
              buffer += decoder.decode(value, { stream: !done });
              buffer = buffer.replace(/\r\n/g, "\n");
              let boundary;
              while ((boundary = buffer.indexOf("\n\n")) >= 0) {
                const frame = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                const payload = frame.split("\n").filter((line) => line.startsWith("data:"))
                  .map((line) => line.slice(5).trimStart()).join("\n");
                if (!payload) continue;
                const event = JSON.parse(payload);
                if (event.type === "error") {
                  defer(Number(event.retry_after_seconds));
                  throw new ChatApiError(typeof event.detail === "string" ? event.detail : "Không thể hoàn tất lượt hội thoại.", false, remaining());
                }
                if (event.type === "complete") {
                  if (typeof event.response !== "string") throw new Error("Missing final response");
                  defer(Number(event.retry_after_seconds));
                  return event as ChatResponse;
                }
                if (["input", "delta", "replace", "response_complete"].includes(event.type)) {
                  await onProgress?.(event as ChatStreamEvent);
                }
              }
              if (done) throw new ChatApiError("Luồng phản hồi bị ngắt trước khi hoàn tất. Không tự động gửi lại yêu cầu.", true);
            }
          } catch (error) {
            if (error instanceof ChatApiError) throw error;
            throw new ChatApiError("Mất kết nối hoặc luồng phản hồi không hợp lệ. Nội dung đã nhận vẫn được giữ lại.", true);
          } finally {
            await reader.cancel().catch(() => {});
            reader.releaseLock();
          }
        }

        let data;
        try {
          data = await response.json();
        } catch {
          throw new ChatApiError(`Backend trả về phản hồi không hợp lệ (HTTP ${response.status}). Vui lòng thử lại sau.`);
        }
        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            throw new ChatApiError("Dịch vụ chưa cấp quyền tư vấn. Nội dung vẫn được giữ; hãy liên hệ hỗ trợ trước khi thử lại.");
          }
          if (response.status === 429) {
            const seconds = Number(data?.retry_after_seconds ?? response.headers.get("Retry-After"));
            defer(Number.isFinite(seconds) && seconds > 0 ? seconds : 30);
          }
          throw new ChatApiError(typeof data?.detail === "string" ? data.detail : `Không xử lý được lượt thoại (HTTP ${response.status}). Vui lòng thử lại sau.`, false, remaining());
        }
        if (!data || typeof data.response !== "string") {
          throw new ChatApiError("Backend chưa trả về phản hồi hội thoại hợp lệ. Vui lòng thử lại sau.");
        }
        defer(Number(data.retry_after_seconds));
        return data as ChatResponse;
      } finally {
        sending = false;
      }
    },
  };
}
