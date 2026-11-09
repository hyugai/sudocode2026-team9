import { readCallBrief, type CallBrief } from "./call-brief.ts";

export const chatStageLabels = {
  processing: "Đang xử lý yêu cầu…",
  transcribing: "Đang nhận dạng ghi âm…",
  identifying: "Đang xác định khách hàng…",
  analyzing: "Đang phân tích ý định…",
  retrieving: "Đang tra cứu dữ liệu…",
  brief: "Đang chuẩn bị call brief…",
  tools: "Đang kiểm tra thông tin liên quan…",
  generating: "Đang soạn câu trả lời…",
  checking: "Đang kiểm tra câu trả lời…",
  saving: "Đang lưu kết quả…",
} as const;
export type ChatStage = keyof typeof chatStageLabels;

export interface DebugInfo {
  intent: string;
  retrieved_knowledge: unknown[];
  steps?: { action: string; rationale: string; tool: string | null; tool_args: unknown }[];
  call_brief?: unknown;
}

interface ChatResponse {
  user_message_id?: string;
  message_id?: string;
  response: string;
  callBrief: CallBrief | null;
  transcript?: string;
  normalized_message?: string;
  debug?: DebugInfo;
  retry_after_seconds?: number;
  latency?: Record<string, unknown>;
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

async function readChatStream(response: Response, onText: (text: string) => void, defer: (seconds: number) => void, onStatus?: (stage: ChatStage) => void) {
  const reader = response.body?.getReader();
  if (!reader) throw new ChatApiError("Không nhận được luồng trả lời.");
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = frame.split("\n");
        const event = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
        const json = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!json) continue; // Heartbeats keep a long tool call connected.
        const data = JSON.parse(json);
        if (event === "status" && typeof data?.stage === "string" && Object.hasOwn(chatStageLabels, data.stage)) onStatus?.(data.stage as ChatStage);
        if (event === "text" && typeof data?.text === "string") onText(data.text);
        if (event === "done") return data;
        if (event === "error") {
          const seconds = Number(data?.retry_after_seconds);
          const retry = data?.status === 429 ? (Number.isFinite(seconds) && seconds > 0 ? seconds : 30) : 0;
          defer(retry);
          throw new ChatApiError(typeof data?.detail === "string" ? data.detail : "Chưa hoàn tất câu trả lời. Hãy kiểm tra lịch sử trước khi gửi lại.", false, retry);
        }
      }
      if (done) break;
    }
  } catch (error) {
    if (error instanceof ChatApiError) throw error;
    throw new ChatApiError("Luồng trả lời bị gián đoạn. Hãy kiểm tra lịch sử trước khi gửi lại.", true);
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  throw new ChatApiError("Chưa xác nhận lưu được kết quả. Hãy kiểm tra lịch sử trước khi gửi lại.", true);
}

export function createChatClient(apiBase: string, fetcher: typeof fetch = fetch, now = Date.now, accountMode = false) {
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
        const response = await fetcher(accountMode ? "/api/health" : `${apiBase}/health`, { signal, cache: "no-store" });
        return response.ok;
      } catch {
        return false;
      }
    },

    async clearSession(conversationId: string): Promise<void> {
      if (sending) throw new ChatApiError("Chờ Synee trả lời trước khi kết thúc hội thoại.");
      if (!conversationId) return;
      try {
        const response = await fetcher(accountMode ? `/api/conversations/${encodeURIComponent(conversationId)}/end` : `${apiBase}/api/sessions/${encodeURIComponent(conversationId)}`, {
          method: accountMode ? "POST" : "DELETE", credentials: "same-origin", signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) throw new ChatApiError(response.status === 401 || response.status === 403
          ? "Dịch vụ chưa cấp quyền kết thúc hội thoại. Dữ liệu trên thiết bị vẫn được giữ."
          : "Chưa kết thúc được hội thoại. Hãy thử lại; dữ liệu vẫn được giữ.");
        const data = await response.json();
        if (accountMode ? data?.status !== "ended" : data?.status !== "cleared" || data.conversation_id !== conversationId) throw new ChatApiError("Dịch vụ chưa xác nhận kết thúc đúng hội thoại. Dữ liệu vẫn được giữ.");
      } catch (e) {
        if (e instanceof ChatApiError) throw e;
        throw new ChatApiError("Không kết nối được dịch vụ để kết thúc hội thoại. Dữ liệu vẫn được giữ.", true);
      }
    },

    async send(turn: ChatTurn, onText?: (text: string) => void, onStatus?: (stage: ChatStage) => void): Promise<ChatResponse | null> {
      // Set synchronously, before the first await, to reject rapid duplicate submits.
      if (sending) return null;
      if (remaining()) throw new ChatApiError("Vui lòng chờ hết thời gian giới hạn trước khi gửi lại.", false, remaining());
      sending = true;
      try {
        let body: BodyInit;
        const headers: Record<string, string> = accountMode ? { "X-Conversation-Mode": "account" } : {};
        if (onText || onStatus) headers.Accept = "text/event-stream";
        if (turn.audioFile) {
          const form = new FormData();
          form.append("conversation_id", turn.conversationId);
          form.append("file", turn.audioFile);
          if (turn.customerPhone) form.append("customer_phone", turn.customerPhone);
          body = form;
        } else {
          headers["Content-Type"] = "application/json";
          body = JSON.stringify({
            conversation_id: turn.conversationId,
            message: turn.message,
            customer_phone: turn.customerPhone || null,
          });
        }

        let response: Response;
        try {
          response = await fetcher(`${accountMode ? "" : apiBase}/api/chat${turn.audioFile ? "/audio" : ""}`, {
            method: "POST", headers: Object.keys(headers).length ? headers : undefined, body, credentials: "same-origin",
          });
        } catch {
          // A lost response does not prove that the backend skipped the turn.
          // Never automatically retry a POST that may have performed agent actions.
          throw new ChatApiError("Mất kết nối với backend. File và nội dung vẫn được giữ lại; hãy chờ kết nối sẵn sàng rồi thử lại.", true);
        }

        let data;
        try {
          data = response.ok && (onText || onStatus) && response.headers.get("content-type")?.includes("text/event-stream")
            ? await readChatStream(response, onText ?? (() => {}), defer, onStatus)
            : await response.json();
        } catch (error) {
          if (error instanceof ChatApiError) throw error;
          throw new ChatApiError(`Backend trả về phản hồi không hợp lệ (HTTP ${response.status}). Vui lòng thử lại sau.`);
        }
        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            throw new ChatApiError(accountMode ? "Phiên đăng nhập đã hết hạn. Nội dung vẫn được giữ; hãy đăng nhập lại." : "Dịch vụ chưa cấp quyền tư vấn. Nội dung vẫn được giữ; hãy liên hệ hỗ trợ trước khi thử lại.");
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
        return { ...data, callBrief: readCallBrief(data.call_brief) ?? readCallBrief(data.debug?.call_brief) } as ChatResponse;
      } finally {
        sending = false;
      }
    },
  };
}
