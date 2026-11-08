export type StoredFeedback = { rating: "positive" | "negative" | null; comment: string };
export type SavedMessage = { id: string; role: "user" | "agent"; content: string; turn_number: number; feedback: StoredFeedback | null };
export type SavedConversation = {
  id: string; status: "active" | "ended"; turn_number: number; customer_phone: string | null;
  created_at: string; updated_at: string; messages: SavedMessage[]; call_brief: unknown; has_more: boolean;
};
export type ConversationSummary = Pick<SavedConversation, "id" | "status" | "turn_number" | "customer_phone" | "updated_at">;
export const accountConversationKey = "synee.account.conversation.v1";

async function request(path: string, method = "GET", body?: unknown) {
  const response = await fetch(`/api/${path}`, {
    method, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000),
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Chưa xử lý được dữ liệu hội thoại. Hãy thử lại.");
  return data;
}

export const conversationApi = {
  create: (phone: string): Promise<ConversationSummary> => request("conversations", "POST", { customer_phone: phone || null }),
  list: (offset = 0): Promise<{ items: ConversationSummary[]; has_more: boolean }> => request(`conversations?limit=20&offset=${offset}`),
  async load(id: string): Promise<SavedConversation> {
    const path = `conversations/${encodeURIComponent(id)}?limit=100`;
    const result: SavedConversation = await request(path);
    let page = result;
    while (page.has_more) {
      page = await request(`${path}&offset=${result.messages.length}`);
      result.messages.push(...page.messages);
    }
    return { ...result, has_more: false };
  },
  putFeedback: (id: string, value: StoredFeedback): Promise<StoredFeedback> => request(`messages/${encodeURIComponent(id)}/feedback`, "PUT", value),
  deleteFeedback: (id: string): Promise<{ status: string }> => request(`messages/${encodeURIComponent(id)}/feedback`, "DELETE"),
};
