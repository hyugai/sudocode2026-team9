import Link from "next/link";
import type { ReactNode } from "react";
import { informationPages, type InformationPageId } from "@/utils/information-pages";

type IconName = InformationPageId | "chat" | "audio" | "order" | "arrow" | "email" | "phone" | "location";

function InformationIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    support: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 .5c0 1.7-2.5 2-2.5 3.5M12 16h.01" /></>,
    privacy: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8 12 3 3 5-6" /></>,
    terms: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>,
    contact: <><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-1 2V11.5a9 9 0 1 1 18 0Z" /><path d="M7 11h.01M12 11h.01M17 11h.01" /></>,
    chat: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /><path d="M8 9h8M8 13h5" /></>,
    audio: <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" /></>,
    order: <><path d="m3 7 9-4 9 4v11l-9 4-9-4ZM3 7l9 4 9-4M12 11v11M7.5 5l9 4" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    email: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 6 9 7 9-7" /></>,
    phone: <path d="m8 3 3 5-3 3a13 13 0 0 0 5 5l3-3 5 3v3a2 2 0 0 1-2 2C9 21 3 15 3 5a2 2 0 0 1 2-2Z" />,
    location: <><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
  };
  return <svg className="information-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function InformationSection({ number, title, children }: { number: string; title: string; children: ReactNode }) {
  return <section className="information-section">
    <h2><span aria-hidden="true">{number}</span>{title}</h2>
    <div className="information-prose">{children}</div>
  </section>;
}

function SupportContent() {
  const questions = [
    { question: "Mình bắt đầu trò chuyện với Synee như thế nào?", answer: <>Chọn <Link href="/ai-chat?mode=text">Chatbot</Link> trên header hoặc nhập câu hỏi tại dashboard. Bạn có thể nói rõ sản phẩm, nhu cầu và ngân sách để Synee gợi ý phù hợp hơn.</> },
    { question: "Gửi file ghi âm trong Chat có khác với Voice không?", answer: <>Trong Chat, bấm biểu tượng micro để chọn file audio, nghe lại rồi bấm Gửi. Synee chuyển giọng nói thành văn bản và xử lý câu hỏi. Chế độ <Link href="/ai-chat?mode=realtime">Voice</Link> dành cho trò chuyện trực tiếp qua microphone.</> },
    { question: "File ghi âm được hỗ trợ có giới hạn gì?", answer: <>Bạn có thể tải WAV, MP3, M4A, FLAC, OGG hoặc WebM, tối đa 25 MB và 120 giây. Nếu file không hợp lệ, hãy chọn lại file ngắn hơn hoặc chuyển sang nhập văn bản.</> },
    { question: "Vì sao nút Gửi chưa sử dụng được?", answer: <>Hãy nhập nội dung hoặc chọn file audio và kiểm tra thông báo kết nối. Nếu dịch vụ chưa sẵn sàng, chờ kết nối lại; nếu đang có thời gian chờ, đợi bộ đếm kết thúc rồi gửi lại. Sau lỗi gửi, nội dung được giữ để bạn tự thử lại.</> },
    { question: "Tại sao Voice không mở được microphone?", answer: <>Hãy cho phép truy cập microphone trong trình duyệt, kiểm tra thiết bị thu âm và dùng kết nối HTTPS hoặc localhost. Nếu dịch vụ Voice chưa sẵn sàng, bạn vẫn có thể chuyển về Chat để nhập câu hỏi hoặc gửi file audio.</> },
    { question: "Mình có thể đặt hàng và thanh toán thật chưa?", answer: <>Giao diện giỏ hàng và đơn hàng hiện phục vụ trải nghiệm demo, chưa thu tiền hoặc giữ hàng. Danh mục sản phẩm đang hiển thị chưa kết nối trực tiếp với luồng đặt hàng demo. Bạn có thể nhờ Synee tư vấn trước khi lựa chọn.</> },
    { question: "Mình xem lại hội thoại và thông tin tư vấn ở đâu?", answer: <>Mở menu Tài khoản để vào <Link href="/account/conversations">Lịch sử hội thoại</Link> hoặc <Link href="/account">Hồ sơ cá nhân</Link>. Đây là phiên khách trong tab hiện tại, chưa có đăng nhập và đồng bộ giữa các thiết bị.</> },
  ];
  return <>
    <div className="information-card-heading"><span className="information-eyebrow">BẮT ĐẦU TỪ ĐÂY</span><h2>Bạn cần hỗ trợ điều gì?</h2><p>Chọn cách phù hợp để tiếp tục trải nghiệm.</p></div>
    <div className="information-shortcuts">
      {[{ href: "/ai-chat?mode=text", icon: "chat" as const, title: "Chat cùng Synee", text: "Tìm sản phẩm, so sánh và hỏi đáp." }, { href: "/ai-chat?mode=realtime", icon: "audio" as const, title: "Trò chuyện bằng Voice", text: "Trao đổi trực tiếp bằng giọng nói." }, { href: "/orders", icon: "order" as const, title: "Đơn hàng demo", text: "Xem lại đơn trong tab hiện tại." }].map(item => <Link className="information-shortcut" href={item.href} key={item.href}><span className="information-icon-tile"><InformationIcon name={item.icon} /></span><h3>{item.title}</h3><p>{item.text}</p><span className="information-shortcut-action">Mở ngay <InformationIcon name="arrow" /></span></Link>)}
    </div>
    <section className="information-faq" aria-labelledby="faq-heading"><h2 id="faq-heading">Câu hỏi thường gặp</h2><div>{questions.map(item => <details key={item.question}><summary>{item.question}<span aria-hidden="true">+</span></summary><p>{item.answer}</p></details>)}</div></section>
    <div className="information-callout"><InformationIcon name="contact" /><div><h3>Bạn cần thêm thông tin?</h3><p>Xem các kênh kết nối và thông tin liên hệ của Synee.</p></div><Link className="information-button secondary" href="/contact">Trang liên hệ <InformationIcon name="arrow" /></Link></div>
  </>;
}

function PrivacyContent() {
  return <>
    <div className="information-note"><InformationIcon name="privacy" /><p>Nội dung dưới đây mô tả cách dữ liệu được sử dụng trong phiên bản demo hiện tại.</p></div>
    <InformationSection number="01" title="Thông tin bạn cung cấp">
      <p>Khi sử dụng Synee, bạn có thể cung cấp tin nhắn, file ghi âm, nội dung trò chuyện bằng Voice, sản phẩm đang quan tâm và số điện thoại tư vấn. Số điện thoại tư vấn là thông tin không bắt buộc, không phải tài khoản đăng nhập.</p>
      <p>Nếu trải nghiệm luồng đặt hàng demo, bạn có thể nhập tên người nhận, số điện thoại và địa chỉ giao hàng. Bạn nên dùng thông tin giả lập khi thử tính năng này.</p>
    </InformationSection>
    <InformationSection number="02" title="Mục đích sử dụng">
      <ul><li>Hiểu câu hỏi và đưa ra gợi ý theo nhu cầu, ngân sách của bạn.</li><li>Chuyển ghi âm thành văn bản và phản hồi bằng giọng nói khi bạn sử dụng tính năng audio.</li><li>Duy trì ngữ cảnh tư vấn, khôi phục bản nháp và hiển thị dữ liệu mua sắm demo.</li></ul>
    </InformationSection>
    <InformationSection number="03" title="Lưu trữ trên trình duyệt">
      <p>Hội thoại, bản nháp, số điện thoại tư vấn và ngữ cảnh sản phẩm được lưu trong phiên của tab để khôi phục khi tải lại trang. File audio đã chọn chỉ được giữ trong bộ nhớ khi trang đang mở và không được khôi phục sau khi tải lại.</p>
      <p>Danh sách sản phẩm trong giỏ demo được lưu trên trình duyệt. Thông tin giao hàng và đơn demo được lưu theo phiên của tab. Những dữ liệu này không được đồng bộ như tài khoản khách hàng.</p>
    </InformationSection>
    <InformationSection number="04" title="Xử lý tại dịch vụ tư vấn">
      <p>Khi bạn bấm Gửi hoặc bắt đầu Voice, nội dung liên quan được chuyển đến dịch vụ tư vấn để xử lý. Tùy cấu hình triển khai, dịch vụ có thể sử dụng nhà cung cấp AI, nhận dạng giọng nói và lưu ngữ cảnh hoặc bộ nhớ khách hàng.</p>
      <p>Xóa dữ liệu trên trình duyệt hoặc kết thúc hội thoại không đồng nghĩa với việc xóa toàn bộ thông tin đã lưu tại dịch vụ. Chính sách lưu giữ phía dịch vụ cần được đơn vị vận hành xác nhận khi triển khai chính thức.</p>
    </InformationSection>
    <InformationSection number="05" title="Quyền kiểm soát của bạn">
      <ul><li>Bạn có thể bỏ qua số điện thoại tư vấn, xem lại audio trước khi gửi hoặc xóa file đã chọn.</li><li>Microphone được yêu cầu khi bắt đầu Voice; bạn có thể tắt tiếng hoặc kết thúc phiên.</li><li>Vào <Link href="/account/conversations">Lịch sử hội thoại</Link> để kết thúc hội thoại hiện tại; dùng cài đặt trình duyệt để xóa dữ liệu website trên thiết bị.</li></ul>
      <p>Nếu cần trao đổi thêm về dữ liệu, xem <Link href="/contact">trang Liên hệ</Link>. Các kênh liên hệ trực tiếp sẽ được bổ sung sau.</p>
    </InformationSection>
  </>;
}

function TermsContent() {
  return <>
    <div className="information-note"><InformationIcon name="terms" /><p>Điều khoản trải nghiệm dành cho bản demo Synee AI và giao diện mua sắm SUDO market.</p></div>
    <InformationSection number="01" title="Phạm vi trải nghiệm">
      <p>Website giới thiệu danh mục sản phẩm và hỗ trợ tư vấn bằng văn bản, file ghi âm hoặc Voice. Các tính năng phụ thuộc vào trạng thái dịch vụ và cấu hình của bản triển khai.</p>
      <p>Trang hồ sơ hiện là hồ sơ khách tư vấn trong tab, chưa phải tài khoản đăng nhập hoặc xác thực danh tính.</p>
    </InformationSection>
    <InformationSection number="02" title="Thông tin sản phẩm và gợi ý AI">
      <p>Ảnh sản phẩm là ảnh minh họa cho bản demo; kiểu dáng thực tế có thể khác. Giá hiển thị chưa áp dụng khuyến mãi. Một số dữ liệu như đánh giá, lượt bán và sắp xếp sản phẩm chưa được cung cấp.</p>
      <p>Phản hồi của Synee mang tính hỗ trợ tham khảo. Bạn nên kiểm tra lại tên sản phẩm, thông số, giá và nội dung ghi âm được nhận dạng trước khi đưa ra quyết định mua sắm.</p>
    </InformationSection>
    <InformationSection number="03" title="Giỏ hàng, đơn hàng và thanh toán">
      <p>Luồng giỏ hàng, xác nhận đơn và theo dõi đơn trên giao diện hiện là demo tại trình duyệt. Thao tác trong luồng này không giữ hàng, thu tiền hoặc tạo yêu cầu giao hàng thật.</p>
      <p>Danh mục sản phẩm hiện tại chưa kết nối trực tiếp với giỏ hàng demo. Thông tin hoặc xác nhận do AI đưa ra cần được đối chiếu với đơn vị vận hành trước khi coi là giao dịch thực tế.</p>
    </InformationSection>
    <InformationSection number="04" title="Sử dụng Chat và Voice">
      <ul><li>Chỉ cung cấp nội dung và ghi âm mà bạn có quyền sử dụng.</li><li>File audio hỗ trợ tối đa 25 MB và 120 giây; Voice cần microphone và kết nối phù hợp.</li><li>Không gửi mật khẩu, mã OTP, thông tin thẻ thanh toán hoặc dữ liệu nhạy cảm không cần thiết cho việc tư vấn.</li><li>Không dùng dịch vụ để gửi nội dung gây hại, giả mạo hoặc làm gián đoạn hệ thống.</li></ul>
    </InformationSection>
    <InformationSection number="05" title="Khi gặp sự cố hoặc cần hỗ trợ">
      <p>Dịch vụ có thể gián đoạn hoặc yêu cầu chờ giữa các lượt gửi. Hãy làm theo thông báo trên màn hình, kiểm tra nội dung trước khi tự gửi lại và tránh gửi trùng yêu cầu.</p>
      <p>Bạn có thể xem <Link href="/support">Hỗ trợ</Link> để tìm hướng dẫn, hoặc đến <Link href="/contact">Liên hệ</Link> để xem các kênh kết nối. Nội dung các trang này sẽ được cập nhật khi phiên bản chính thức bổ sung tính năng và thông tin vận hành.</p>
    </InformationSection>
  </>;
}

function ContactContent() {
  return <>
    <section className="information-contact-feature" aria-labelledby="contact-chat-heading"><span className="information-icon-tile"><InformationIcon name="chat" /></span><div><span className="information-eyebrow">TRỢ LÝ MUA SẮM CỦA BẠN</span><h2 id="contact-chat-heading">Bắt đầu cùng Synee AI</h2><p>Bạn cần tìm sản phẩm, so sánh lựa chọn hay tìm hiểu tính năng? Synee có thể hỗ trợ ngay trong cuộc trò chuyện.</p><Link className="information-button" href="/ai-chat?mode=text">Trò chuyện với Synee <InformationIcon name="arrow" /></Link></div></section>
    <section aria-labelledby="contact-channels-heading"><div className="information-card-heading"><h2 id="contact-channels-heading">Thông tin liên hệ</h2><p>Các kênh liên hệ trực tiếp sẽ được bổ sung khi có thông tin chính thức.</p></div><div className="information-contact-channels">
      {[{ icon: "email" as const, title: "Email hỗ trợ", text: "Tiếp nhận câu hỏi và góp ý." }, { icon: "phone" as const, title: "Hotline", text: "Trao đổi trực tiếp với đội ngũ hỗ trợ." }, { icon: "location" as const, title: "Địa chỉ", text: "Thông tin địa điểm liên hệ." }].map(item => <div className="information-contact-channel" key={item.title}><span className="information-icon-tile"><InformationIcon name={item.icon} /></span><h3>{item.title}</h3><p>{item.text}</p><span className="information-pending">Sẽ cập nhật</span></div>)}
    </div></section>
    <div className="information-callout"><InformationIcon name="support" /><div><h3>Tìm câu trả lời nhanh hơn</h3><p>Hướng dẫn Chat, gửi ghi âm, Voice và các câu hỏi thường gặp.</p></div><Link className="information-button secondary" href="/support">Xem hướng dẫn <InformationIcon name="arrow" /></Link></div>
  </>;
}

export function InformationPage({ page }: { page: InformationPageId }) {
  const info = informationPages.find(item => item.id === page)!;
  const titles: Record<InformationPageId, string> = {
    support: "Luôn sẵn sàng đồng hành cùng bạn.",
    privacy: "Rõ ràng về thông tin của bạn.",
    terms: "Trải nghiệm rõ ràng, lựa chọn an tâm.",
    contact: "Kết nối với Synee.",
  };
  return <div className="information-page">
    <div className="information-hero"><div className="container"><nav className="information-breadcrumb" aria-label="Đường dẫn"><Link href="/">Trang chủ</Link><span aria-hidden="true">/</span><span aria-current="page">{info.title}</span></nav><span className="information-hero-label"><InformationIcon name={page} />{info.title}</span><h1>{titles[page]}</h1><p>{info.description}</p></div></div>
    <div className="information-layout container"><aside className="information-sidebar"><nav aria-label="Trung tâm thông tin"><p>THÔNG TIN & HỖ TRỢ</p>{informationPages.map(item => <Link href={item.href} key={item.id} aria-current={page === item.id ? "page" : undefined}><InformationIcon name={item.id} /><span>{item.title}</span><InformationIcon name="arrow" /></Link>)}</nav><div className="information-sidebar-note"><span className="information-icon-tile"><InformationIcon name="chat" /></span><h2>Có Synee bên bạn</h2><p>Tư vấn theo nhu cầu, tìm lựa chọn vừa ngân sách.</p><Link href="/ai-chat?mode=text">Mở chatbot <InformationIcon name="arrow" /></Link></div></aside>
      <div className="information-content">{page === "support" ? <SupportContent /> : page === "privacy" ? <PrivacyContent /> : page === "terms" ? <TermsContent /> : <ContactContent />}</div>
    </div>
  </div>;
}
