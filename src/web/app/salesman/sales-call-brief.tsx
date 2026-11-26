import type { CallBrief } from "@/utils/call-brief";
import { Icon } from "../ai-chat/icons";

export function SalesCallBrief({ brief, loading, error }: { brief: CallBrief | null; loading: boolean; error: boolean }) {
  const sections = brief ? [
    { title: "Nhu cầu", icon: "search" as const, items: brief.needs },
    { title: "Băn khoăn", icon: "message" as const, items: brief.objections },
    { title: "Cần xử lý tiếp", icon: "plan" as const, items: brief.unresolvedIssues },
  ] : [];

  return <aside className="sales-brief-sidebar" aria-labelledby="sales-brief-title" aria-busy={loading}>
    <header className="sales-brief-heading"><span>Phiên tư vấn</span><h2 id="sales-brief-title">Call brief</h2><p>Tóm tắt ngữ cảnh cuộc trò chuyện</p></header>
    <p className="sales-brief-status" role="status"><Icon name={loading ? "more" : brief ? "check" : "document"} />{loading ? "Đang tải call brief…" : error ? "Chưa tải được call brief" : brief ? "Bản lưu của hội thoại đang chọn" : "Chưa có dữ liệu call brief"}</p>
    {brief ? <div className="sales-brief">
      <section className="sales-brief-summary"><h3><Icon name="document" />Tóm tắt</h3><p>{brief.summary || "Chưa có tóm tắt."}</p></section>
      {sections.map(section => <section key={section.title}><h3><Icon name={section.icon} />{section.title}<span>{section.items.length}</span></h3>{section.items.length ? <ul>{section.items.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p className="sales-brief-muted">Chưa ghi nhận.</p>}</section>)}
    </div> : <div className="sales-brief-empty"><span><Icon name="note" /></span><h3>{loading ? "Đang đọc bản lưu" : error ? "Chưa đọc được bản lưu" : "Chưa có call brief"}</h3><p>{loading ? "Nội dung sẽ hiển thị khi tải hội thoại hoàn tất." : error ? "Hãy thử lại ở phần chi tiết hội thoại." : "Hội thoại này chưa lưu call brief. Dữ liệu không được tạo lại khi xem."}</p></div>}
  </aside>;
}
