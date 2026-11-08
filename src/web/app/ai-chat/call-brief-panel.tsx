import type { ReactNode } from "react";
import type { CallBrief } from "@/utils/call-brief";
import { Icon } from "./icons";

export function CallBriefPanel({ brief, loading, error, hasConversation, children }: { brief: CallBrief | null; loading: boolean; error: boolean; hasConversation: boolean; children: ReactNode }) {
  const sections = brief ? [
    { title: "Nhu cầu", icon: "search" as const, items: brief.needs, empty: "Chưa ghi nhận nhu cầu cụ thể." },
    { title: "Băn khoăn", icon: "message" as const, items: brief.objections, empty: "Chưa ghi nhận băn khoăn." },
    { title: "Cần xử lý tiếp", icon: "plan" as const, items: brief.unresolvedIssues, empty: "Chưa có vấn đề cần xử lý tiếp." },
  ] : [];
  return <div className="ai-details ai-call-brief">
    <div className="ai-details-heading"><div><span>Phiên tư vấn</span><strong>Call brief</strong><p>Tóm tắt ngữ cảnh cuộc trò chuyện</p></div></div>
    <p className={`ai-brief-status${error && !loading ? " has-error" : ""}`} role="status" aria-live="polite"><Icon name={loading ? "more" : brief ? "check" : "document"} />{loading ? "Đang cập nhật call brief…" : error && brief ? "Chưa cập nhật được. Đang hiển thị bản từ lượt trước." : brief ? "Đã nhận call brief từ dịch vụ" : "Chưa có dữ liệu call brief"}</p>
    {brief ? <>
      <section className="ai-brief-summary"><h2><Icon name="document" />Tóm tắt</h2><p>{brief.summary || "Chưa có nội dung tóm tắt."}</p></section>
      {sections.map(section => <section className="ai-brief-section" key={section.title}><h2><Icon name={section.icon} />{section.title}<span>{section.items.length}</span></h2>{section.items.length ? <ul>{section.items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="ai-brief-section-empty">{section.empty}</p>}</section>)}
    </> : <div className="ai-brief-empty"><span><Icon name="note" /></span><h2>{loading ? "Đang tổng hợp ngữ cảnh" : "Call brief sẽ xuất hiện tại đây"}</h2><p>{loading ? "Nội dung sẽ hiển thị khi lượt tư vấn hoàn tất." : hasConversation ? "Chưa nhận được call brief cho hội thoại này. Các tin nhắn của bạn vẫn được giữ nguyên." : "Bắt đầu trò chuyện để xem tóm tắt, nhu cầu và những nội dung cần theo dõi khi có dữ liệu."}</p></div>}
    <details className="ai-brief-session"><summary><Icon name="sliders" />Thông tin phiên<Icon name="chevron" /></summary><div>{children}</div></details>
  </div>;
}
