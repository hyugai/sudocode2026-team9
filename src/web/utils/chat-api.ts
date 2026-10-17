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
          if (turn.customerPhone) form.append("customer_phone", turn.customerPhone);
          body = form;
        } else {
          headers = { "Content-Type": "application/json" };
          body = JSON.stringify({
            conversation_id: turn.conversationId,
            message: turn.message,
            customer_phone: turn.customerPhone || null,
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

        let data;
        try {
          data = await response.json();
        } catch {
          throw new ChatApiError(`Backend trả về phản hồi không hợp lệ (HTTP ${response.status}). Vui lòng thử lại sau.`);
        }
        if (!response.ok) {
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
