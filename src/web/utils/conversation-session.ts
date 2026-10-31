/** Current-tab guest continuity only. This is not an authentication session. */
export const conversationStorageKey = "synee.guest.conversation.v1";
export type GuestSession = {
  messages: { role: "user" | "agent"; text: string }[];
  sessionId: string;
  input: string;
  customerPhone: string;
  voicePreview: boolean;
  consultation: { sku: string; name: string; price: string; quantity: number } | null;
};

export function readGuestSession(raw: string | null): GuestSession | null {
  if (!raw) return null;
  if (raw.length > 2_000_000) throw new Error("Hội thoại đã lưu quá lớn. Hãy xóa phiên trên thiết bị này để bắt đầu lại.");
  const s = JSON.parse(raw);
  const valid = s && s.version === 1 && Array.isArray(s.messages) && s.messages.length <= 300
    && s.messages.every((m: { role?: unknown; text?: unknown }) => m && (m.role === "user" || m.role === "agent") && typeof m.text === "string" && m.text.length <= 100000)
    && typeof s.sessionId === "string" && (!s.sessionId || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s.sessionId))
    && typeof s.input === "string" && s.input.length <= 100000
    && typeof s.customerPhone === "string" && s.customerPhone.length <= 30 && typeof s.voicePreview === "boolean";
  const c = s?.consultation;
  if (!valid || (c !== null && (!c || typeof c.sku !== "string" || c.sku.length > 100 || typeof c.name !== "string" || c.name.length > 500 || typeof c.price !== "string" || c.price.length > 100 || !Number.isSafeInteger(c.quantity) || c.quantity < 1 || c.quantity > 10000))) {
    throw new Error("Không đọc được hội thoại đã lưu. Bạn vẫn có thể tư vấn trong phiên mới.");
  }
  return { messages: s.messages, sessionId: s.sessionId, input: s.input, customerPhone: s.customerPhone, voicePreview: s.voicePreview, consultation: c };
}

export function writeGuestSession(session: GuestSession): string {
  const { sessionId, input, customerPhone, voicePreview, consultation } = session;
  const raw = JSON.stringify({ sessionId, input, customerPhone, voicePreview, consultation, messages: session.messages.slice(-300), version: 1 });
  // Validate the same bounds before writing, including the total storage budget.
  readGuestSession(raw);
  return raw;
}
