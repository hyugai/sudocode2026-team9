export type HistorySource = "chat" | "voice";
export type HistoryItem = {
  source: HistorySource; id: string; user_id: string | null; user_name: string | null;
  user_email: string | null; customer_id: string | null; customer_phone: string | null;
  status: string; turn_number: number; created_at: string; updated_at: string;
};
export type HistoryMessage = {
  id: string; role: "user" | "agent"; content: string; created_at?: string; incomplete?: boolean;
};
export type HistoryDetail = {
  id: string; source: HistorySource; status: string; updated_at: string; customer_id: string | null;
  customer_phone: string | null; turn_number: number | null;
  user: { id: string; name: string; email: string } | null;
  call_brief: unknown; memory: Record<string, unknown> | null; messages: HistoryMessage[];
  has_more: boolean; next_offset: number; snapshot_at?: string | null;
};
export type HistoryPage = { items: HistoryItem[]; has_more: boolean; total: number };
