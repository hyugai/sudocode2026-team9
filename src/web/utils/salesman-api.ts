import type { HistoryDetail, HistoryPage, HistorySource } from "./salesman-types.ts";

export class SalesmanApiError extends Error {
  readonly status: number;
  constructor(message: string, status = 0) { super(message); this.status = status; }
}

export function createSalesmanClient(fetcher: typeof fetch = fetch) {
  async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
      response = await fetcher(`/api/salesman/conversations${path}`, {
        credentials: "same-origin", cache: "no-store",
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new SalesmanApiError("Không tải được lịch sử. Kiểm tra kết nối rồi thử lại.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new SalesmanApiError(typeof data?.detail === "string" ? data.detail : "Chưa tải được lịch sử. Hãy thử lại.", response.status);
    if (!data || typeof data !== "object") throw new SalesmanApiError("Dữ liệu lịch sử không hợp lệ.");
    return data as T;
  }
  return {
    list: (q: string, source: string, offset = 0, signal?: AbortSignal) => request<HistoryPage>(`?${new URLSearchParams({ q, source, limit: "20", offset: String(offset) })}`, signal),
    get: (source: HistorySource, id: string, offset = 0, signal?: AbortSignal) => request<HistoryDetail>(`/${source}/${encodeURIComponent(id)}?limit=50&offset=${offset}`, signal),
  };
}
