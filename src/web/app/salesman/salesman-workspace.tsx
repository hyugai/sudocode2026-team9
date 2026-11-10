"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon } from "../ai-chat/icons";
import { readCallBrief } from "@/utils/call-brief";
import { salesmanDemo } from "@/utils/salesman-demo";
import type { HistoryDetail, HistoryItem } from "@/utils/salesman-types";

const date = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Chưa có thời gian" : parsed.toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" });
};
const title = (item: HistoryItem) => item.user_name || item.customer_phone || "Khách Voice";
const keyOf = (item: { source: string; id: string }) => `${item.source}:${item.id}`;
const memorySections = [
  ["customer_memory", "Memory khách hàng", "Thông tin khách hàng được agent nạp và lưu trong phiên."],
  ["working_memory", "Ngữ cảnh đang xử lý", "Thông tin agent giữ để xử lý các lượt trao đổi."],
  ["memory_deltas", "Thông tin mới ghi nhận", "Các thay đổi memory được lưu cùng checkpoint."],
  ["customer_profile", "Hồ sơ đã nạp", "Hồ sơ khách hàng tại thời điểm hội thoại được lưu."],
  ["past_history", "Lịch sử tham chiếu", "Dữ liệu lịch sử đã cung cấp cho agent."],
  ["retrieved_data", "Dữ liệu truy xuất", "Kiến thức, lịch sử và chương trình ưu đãi đã truy xuất."],
] as const;
const tabs = [["messages", "Hội thoại"], ["brief", "Call brief"], ["memory", "Memory agent"]] as const;
type Tab = typeof tabs[number][0];

export function SalesmanWorkspace() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [revision, setRevision] = useState(0);
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [nextOffset, setNextOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<HistoryItem | null>(null);
  const [loadedDetail, setDetail] = useState<HistoryDetail | null>(null);
  const [detailRevision, setDetailRevision] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [moreMessages, setMoreMessages] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [tab, setTab] = useState<Tab>("messages");
  const listRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const detail = selected && loadedDetail?.id === selected.id && loadedDetail.source === selected.source ? loadedDetail : null;

  useEffect(() => {
    const controller = new AbortController();
    listRequest.current = controller;
    // Reset the previous query's presentation before subscribing to this request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true); setPaging(false); setError(""); setItems([]); setHasMore(false); setTotal(0);
    void salesmanDemo.list(query, source, 0, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setItems(page.items); setTotal(page.total); setHasMore(page.has_more); setNextOffset(page.items.length);
      setSelected(previous => page.items.find(item => previous && keyOf(item) === keyOf(previous)) ?? page.items[0] ?? null);
    }).catch(reason => { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Chưa tải được lịch sử."); setSelected(null); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, source, revision]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    detailRequest.current = controller;
    // The request owns its loading state; cleanup aborts every stale response.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDetail(null); setDetailLoading(true); setMoreMessages(false); setDetailError("");
    void salesmanDemo.get(selected.source, selected.id, 0, controller.signal).then(value => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch(reason => { if (!controller.signal.aborted) setDetailError(reason instanceof Error ? reason.message : "Chưa tải được hội thoại."); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selected, detailRevision]);

  const loadMore = async () => {
    const controller = listRequest.current;
    if (!controller || controller.signal.aborted || paging || loading) return;
    setPaging(true); setError("");
    try {
      const page = await salesmanDemo.list(query, source, nextOffset, controller.signal);
      if (controller.signal.aborted) return;
      setItems(previous => [...previous, ...page.items.filter(item => !previous.some(old => keyOf(old) === keyOf(item)))]);
      setHasMore(page.has_more); setNextOffset(nextOffset + page.items.length); setTotal(page.total);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Chưa tải được trang tiếp theo."); }
    finally { if (!controller.signal.aborted) setPaging(false); }
  };
  const loadMessages = async () => {
    const controller = detailRequest.current;
    if (!detail || !controller || controller.signal.aborted || moreMessages) return;
    setMoreMessages(true); setDetailError("");
    try {
      const page = await salesmanDemo.get(detail.source, detail.id, detail.next_offset, controller.signal);
      if (controller.signal.aborted) return;
      setDetail(previous => previous && ({ ...page, messages: [...previous.messages,
        ...page.messages.filter(message => !previous.messages.some(old => old.id === message.id))] }));
    } catch (reason) { if (!controller.signal.aborted) setDetailError(reason instanceof Error ? reason.message : "Chưa tải được tin nhắn."); }
    finally { if (!controller.signal.aborted) setMoreMessages(false); }
  };

  const brief = readCallBrief(detail?.call_brief);

  return <main className="sales-workspace">
    <header className="sales-header"><div className="sales-brand"><span><Icon name="spark" /></span><div><strong>Synee AI</strong><small>Salesman mode</small></div></div>
      <span className="sales-read-only"><Icon name="shield" />Chỉ xem</span>
      <div className="sales-account"><span><strong>Salesman demo</strong><small>Bản xem trước giao diện</small></span><Link href="/" prefetch={false}>Về Dashboard</Link></div>
    </header>
    <div className="sales-demo-note"><strong>Dữ liệu mẫu</strong><p>Bạn đang xem bản demo với các khách hàng và hội thoại minh họa.</p></div>
    <div className="sales-layout"><aside className="sales-sidebar" aria-label="Danh sách hội thoại">
      <div className="sales-sidebar-heading"><h1>Lịch sử hội thoại</h1><p>Xem lại các phiên Chat và Voice của khách hàng.</p></div>
      <form className="sales-search" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); setRevision(value => value + 1); }}><label htmlFor="sales-search">Tìm khách hàng hoặc hội thoại</label><div><input id="sales-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Tên, email, SĐT hoặc mã phiên" maxLength={200} /><button type="submit" aria-label="Tìm hội thoại"><Icon name="search" /></button></div></form>
      <label className="sales-filter" htmlFor="sales-source">Nguồn hội thoại<select id="sales-source" value={source} onChange={event => setSource(event.target.value)}><option value="all">Tất cả nguồn</option><option value="chat">Chat / gửi ghi âm</option><option value="voice">Realtime Voice</option></select></label>
      <div className="sales-list-heading"><p role="status">{loading ? "Đang tải lịch sử…" : `${total} hội thoại`}</p><button type="button" onClick={() => setRevision(value => value + 1)} disabled={loading}>Làm mới</button></div>
      {error && <p className="sales-error" role="alert">{error} <button type="button" onClick={() => setRevision(value => value + 1)}>Thử lại</button></p>}
      {!loading && !items.length && !error && <p className="sales-empty-list">Không có hội thoại phù hợp.</p>}
      <div className="sales-conversations">{items.map(item => <button type="button" key={keyOf(item)} className="sales-conversation" aria-pressed={!!selected && keyOf(selected) === keyOf(item)} onClick={() => { setSelected(item); setTab("messages"); if (matchMedia("(max-width: 840px)").matches) document.getElementById("sales-review")?.focus(); }}>
        <span className="sales-item-heading"><strong>{title(item)}</strong><small>{item.source === "voice" ? "Voice" : "Chat"}</small></span><span>{item.user_email || item.customer_phone || item.customer_id || "Chưa có thông tin khách"}</span><small>{date(item.updated_at)} · {item.turn_number} lượt</small><small>{item.status === "ended" ? "Đã kết thúc" : item.source === "voice" ? "Nhật ký đã lưu" : "Đang hoạt động"}</small>
      </button>)}</div>
      {hasMore && <button className="sales-load-more" type="button" disabled={paging || loading} onClick={() => void loadMore()}>{paging ? "Đang tải…" : "Tải thêm hội thoại"}</button>}
    </aside>
    <section id="sales-review" className="sales-review" tabIndex={-1} aria-label="Chi tiết hội thoại">
      {!selected ? <div className="sales-welcome"><span><Icon name="message" /></span><h2>{loading ? "Đang tải hội thoại…" : "Chọn một hội thoại"}</h2><p>Xem nội dung trao đổi, call brief và memory agent đã ghi nhận.</p></div> : <>
        <header className="sales-review-heading"><div><span>{selected.source === "voice" ? "Realtime Voice" : "Chat / ghi âm"}</span><h2>{title(selected)}</h2><p>{detail?.user?.email || selected.user_email || selected.customer_phone || "Chưa có thông tin liên hệ"}</p><small>Mã phiên: {selected.id}</small></div><button type="button" disabled={detailLoading} onClick={() => setDetailRevision(value => value + 1)}>Làm mới dữ liệu</button></header>
        <p className="sales-snapshot-note">{detail ? `Hội thoại cập nhật: ${date(detail.updated_at)}.${detail.memory ? ` Call brief / memory: ${date(detail.snapshot_at || detail.updated_at)}.` : " Chưa có snapshot memory."}` : "Đang đọc bản lưu hội thoại…"}</p>
        <div className="sales-tabs" role="tablist" aria-label="Nội dung xem">{tabs.map(([value, label], index) => <button key={value} type="button" id={`sales-tab-${value}`} role="tab" aria-selected={tab === value} aria-controls="sales-tab-panel" tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)} onKeyDown={event => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
          if (next < 0) return; event.preventDefault(); setTab(tabs[next][0]); document.getElementById(`sales-tab-${tabs[next][0]}`)?.focus();
        }}>{label}</button>)}</div>
        {detailLoading && <p className="sales-loading" role="status">Đang tải nội dung…</p>}
        {detailError && <p className="sales-error" role="alert">{detailError} <button type="button" onClick={() => setDetailRevision(value => value + 1)}>Thử lại</button></p>}
        <div id="sales-tab-panel" className="sales-tab-panel" role="tabpanel" aria-labelledby={`sales-tab-${tab}`} tabIndex={0}>
          {detail && tab === "messages" && <>{!detail.messages.length && <p className="sales-empty">Chưa có tin nhắn được lưu.</p>}<ol className="sales-messages">{detail.messages.map(message => <li key={message.id} className={`sales-message ${message.role}`}><div><strong>{message.role === "user" ? "Khách hàng" : "Synee AI"}</strong>{message.incomplete && <span>Chưa hoàn tất / bị ngắt</span>}</div><p>{message.content}</p></li>)}</ol>{detail.has_more && <button type="button" className="sales-load-more" disabled={moreMessages} onClick={() => void loadMessages()}>{moreMessages ? "Đang tải…" : "Tải thêm tin nhắn"}</button>}</>}
          {detail && tab === "brief" && (brief ? <div className="sales-brief"><section><h3>Tóm tắt</h3><p>{brief.summary || "Chưa có tóm tắt."}</p></section>{[["Nhu cầu", brief.needs], ["Băn khoăn", brief.objections], ["Cần xử lý tiếp", brief.unresolvedIssues]].map(([label, values]) => <section key={String(label)}><h3>{String(label)}</h3>{(values as string[]).length ? <ul>{(values as string[]).map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>Chưa ghi nhận.</p>}</section>)}</div> : <p className="sales-empty">Hội thoại này chưa lưu call brief. Dữ liệu không được tạo lại khi xem.</p>)}
          {detail && tab === "memory" && (detail.memory ? <div className="sales-memory"><p>Thông tin agent đã ghi nhận và ngữ cảnh đã sử dụng. Nội dung bên dưới là dữ liệu minh họa của hội thoại đang chọn.</p>{memorySections.map(([key, label, description]) => <details key={`${detail.source}:${detail.id}:${key}`} open={key === "customer_memory"}><summary>{label}</summary><p>{description}</p>{detail.memory?.[key] == null ? <p>Chưa ghi nhận.</p> : <pre>{JSON.stringify(detail.memory[key], null, 2)}</pre>}</details>)}</div> : <p className="sales-empty">Hội thoại này chưa lưu snapshot memory. Các nhật ký Voice cũ có thể chỉ chứa transcript.</p>)}
        </div>
      </>}
    </section></div>
  </main>;
}
