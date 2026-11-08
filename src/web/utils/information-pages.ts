export const informationPages = [
  { id: "support", href: "/support", title: "Hỗ trợ", description: "Hướng dẫn sử dụng Synee AI và giải đáp các câu hỏi thường gặp." },
  { id: "privacy", href: "/privacy", title: "Chính sách bảo mật", description: "Tìm hiểu cách thông tin tư vấn, hội thoại và ghi âm được xử lý." },
  { id: "terms", href: "/terms", title: "Điều khoản", description: "Thông tin cần biết khi trải nghiệm mua sắm và trò chuyện cùng Synee AI." },
  { id: "contact", href: "/contact", title: "Liên hệ", description: "Kết nối với Synee và tìm kênh hỗ trợ phù hợp với bạn." },
] as const;

export type InformationPageId = typeof informationPages[number]["id"];
