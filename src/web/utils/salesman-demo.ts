import type { HistoryDetail, HistoryItem, HistoryPage, HistorySource } from "./salesman-types";

// Synthetic fixtures only. This preview never reads accounts, storage or the API.
type DemoConversation = { item: HistoryItem; detail: HistoryDetail };
type Sample = {
  id: string; name: string; email: string; phone: string; source: HistorySource;
  time: string; status?: string; transcript: string[]; summary?: string;
  needs?: string[]; objections?: string[]; nextSteps?: string[];
  memory?: Record<string, unknown> | null; interrupted?: boolean;
};

const samples: Sample[] = [
  {
    id: "demo-chat-001", name: "Nguyễn Minh Anh", email: "minhanh@example.invalid", phone: "090***1201",
    source: "chat", time: "2026-11-10T03:20:00Z",
    transcript: [
      "Mình đang tìm máy lọc không khí cho phòng ngủ, nhà có em bé.",
      "Mình có thể giúp bạn so sánh các lựa chọn. Phòng của bạn rộng khoảng bao nhiêu mét vuông?",
      "Khoảng 28–30 m², ngân sách tối đa 5 triệu.",
      "Mình ghi nhận phòng khoảng 30 m², ưu tiên dùng cho gia đình có em bé. Bạn có cần máy chạy êm khi ngủ không?",
      "Có nhé. Mình muốn máy chạy êm, có khóa trẻ em và dễ thay màng lọc.",
      "Theo danh mục minh họa, AirPure Y phù hợp diện tích này và có khóa trẻ em. Giá mẫu là 5.200.000đ, hơi cao hơn ngân sách của bạn.",
      "Mẫu AirPure X thì sao? Mình cũng muốn biết tiền thay màng lọc nữa.",
      "AirPure X có giá mẫu 4.890.000đ, phù hợp phòng nhỏ hơn. Mình đã ghi nhận cần kiểm tra chi phí màng lọc và độ ồn của cả hai mẫu trước khi tư vấn tiếp.",
      "Nếu Y có ưu đãi thì gửi mình. Mình chưa đặt hàng ngay đâu.",
      "Mình ghi nhận bạn đang cân nhắc, chưa xác nhận đặt hàng. Mình sẽ lưu yêu cầu kiểm tra ưu đãi của AirPure Y và chi phí sử dụng để nhân viên hỗ trợ tiếp.",
      "Liên hệ sau 18 giờ giúp mình, ban ngày mình đi làm.",
      "Đã ghi nhận khung giờ sau 18:00. Bạn cần bảng so sánh AirPure X / Y, ưu đãi của Y và chi phí thay màng lọc; chưa có đơn hàng được tạo.",
    ],
    summary: "Khách tìm máy lọc không khí cho phòng ngủ 28–30 m², có em bé. Ngân sách khoảng 5 triệu, đang cân nhắc AirPure X và Y; chưa chốt đơn. Muốn nhận tư vấn sau 18:00.",
    needs: ["Phòng ngủ 28–30 m², có em bé", "Chạy êm, khóa trẻ em, dễ thay màng lọc", "Ngân sách tối đa 5.000.000đ", "Liên hệ sau 18:00"],
    objections: ["Giá AirPure Y vượt ngân sách", "Chưa rõ chi phí thay màng lọc và độ ồn thực tế"],
    nextSteps: ["Kiểm tra ưu đãi AirPure Y", "Gửi bảng so sánh X / Y và chi phí màng lọc"],
    memory: {
      customer_memory: { nhu_cau: "Máy lọc không khí phòng ngủ", dien_tich_m2: "28–30", ngan_sach_vnd: 5000000, gia_dinh: "Có em bé", uu_tien: ["Chạy êm", "Khóa trẻ em", "Dễ thay màng lọc"], gio_lien_he: "Sau 18:00", trang_thai: "Đang cân nhắc, chưa đặt hàng" },
      working_memory: { san_pham_dang_so_sanh: ["AirPure X", "AirPure Y"], buoc_tiep_theo: "Kiểm tra ưu đãi và tổng chi phí sử dụng", da_xac_nhan_dat_hang: false },
      memory_deltas: [{ thong_tin: "Ngân sách", gia_tri: "5.000.000đ", nguon: "Lượt 2" }, { thong_tin: "Khung giờ liên hệ", gia_tri: "Sau 18:00", nguon: "Lượt 6" }],
      customer_profile: { ten: "Nguyễn Minh Anh (mẫu)", so_dien_thoai: "090***1201", nhom: "Khách đang tìm hiểu", don_hang_truoc: 0 },
      past_history: { so_phien_tham_chieu: 0, ghi_chu: "Lần tư vấn đầu tiên trong dữ liệu mẫu" },
      retrieved_data: { nguon: "Danh mục sản phẩm minh họa", san_pham: [{ sku: "SKU-AP-X", gia_mau_vnd: 4890000 }, { sku: "SKU-AP-Y", gia_mau_vnd: 5200000 }], chua_xac_minh: ["Ưu đãi hiện hành", "Giá màng lọc", "Độ ồn thực tế"] },
    },
  },
  {
    id: "demo-voice-002", name: "Trần Hoàng Nam", email: "hoangnam@example.invalid", phone: "091***2402",
    source: "voice", time: "2026-11-10T02:05:00Z", status: "ended",
    transcript: ["Anh muốn mua robot hút bụi cho căn hộ 70 m².", "Anh ưu tiên hút bụi hay cả lau nhà? Nhà mình có thú cưng không ạ?", "Có mèo, cần hút lông tốt. Tầm 8 triệu thôi.", "Em ghi nhận căn hộ 70 m², có mèo và ngân sách 8 triệu. Anh có muốn nhân viên gửi mẫu có chống rối lông không?", "Gửi hai mẫu để anh so sánh, chưa cần đặt hàng.", "Dạ, em lưu yêu cầu so sánh hai mẫu robot chống rối lông. Chưa có đơn hàng được xác nhận."],
    summary: "Khách muốn robot hút bụi cho căn hộ 70 m², có mèo. Ngân sách 8 triệu, muốn so sánh hai mẫu chống rối lông; chưa đặt hàng.",
    needs: ["Hút lông mèo tốt, chống rối", "Căn hộ 70 m²", "Ngân sách khoảng 8 triệu"], objections: ["Muốn so sánh trước khi chọn"], nextSteps: ["Gửi hai mẫu phù hợp và chính sách bảo hành"],
    memory: { customer_memory: { nha_o: "Căn hộ 70 m²", thu_cung: "Mèo", ngan_sach_vnd: 8000000, san_pham_quan_tam: "Robot hút bụi" }, working_memory: { muc_tieu: "So sánh 2 mẫu chống rối lông", da_xac_nhan_dat_hang: false }, memory_deltas: [{ thong_tin: "Thú cưng", gia_tri: "Mèo", nguon: "Transcript Voice lượt 2" }], customer_profile: { ten: "Trần Hoàng Nam (mẫu)", so_dien_thoai: "091***2402" }, past_history: [], retrieved_data: { nguon: "Danh mục mẫu", ket_qua: ["Robot Clean R1", "Robot Clean R2"] } },
  },
  {
    id: "demo-chat-003", name: "Lê Thu Hà", email: "thuha@example.invalid", phone: "093***3603",
    source: "chat", time: "2026-11-09T10:35:00Z", status: "ended",
    transcript: ["Máy lọc mua tháng trước bao giờ cần thay màng lọc?", "Bạn có thể cho mình biết mẫu máy và tình trạng đèn báo không?", "AirPure Mini, đèn chưa báo nhưng mình thấy nhiều bụi.", "Mình ghi nhận máy AirPure Mini chưa báo thay lọc. Nhân viên sẽ gửi hướng dẫn vệ sinh và xác nhận chu kỳ thay màng theo hướng dẫn của mẫu máy."],
    summary: "Khách đã mua AirPure Mini, hỏi cách vệ sinh và thời điểm thay màng. Chưa có đèn báo thay lọc.", needs: ["Hướng dẫn vệ sinh", "Xác nhận chu kỳ thay màng lọc"], nextSteps: ["Gửi hướng dẫn đúng model AirPure Mini"],
    memory: { customer_memory: { san_pham_da_mua: "AirPure Mini", van_de: "Bám bụi, chưa có đèn cảnh báo" }, working_memory: { intent: "Hỗ trợ sau bán hàng" }, memory_deltas: [], customer_profile: { ten: "Lê Thu Hà (mẫu)", nhom: "Khách quay lại" }, past_history: [{ id: "demo-chat-006", tom_tat: "Đã tìm hiểu AirPure Mini" }], retrieved_data: { tai_lieu: "Hướng dẫn sử dụng AirPure Mini (mẫu)" } },
  },
  {
    id: "demo-voice-004", name: "Phạm Quốc Bảo", email: "quocbao@example.invalid", phone: "094***4804",
    source: "voice", time: "2026-11-09T08:10:00Z", status: "ended", interrupted: true,
    transcript: ["Mình muốn hỏi nồi chiên cho nhà bốn người.", "Bạn muốn dung tích khoảng bao nhiêu lít và có ngân sách dự kiến chưa?", "Khoảng hai triệu, mình đang…"],
    memory: null,
  },
  {
    id: "demo-chat-005", name: "Võ Ngọc Linh", email: "ngoclinh@example.invalid", phone: "096***5005",
    source: "chat", time: "2026-11-09T04:45:00Z",
    transcript: ["Có máy hút ẩm cho phòng 20 m² không?", "Mình ghi nhận phòng 20 m². Bạn muốn ưu tiên độ ồn thấp hay khả năng hong quần áo?", "Cả hai, tầm 4 triệu nhé.", "Mình lưu nhu cầu máy hút ẩm chạy êm và hong quần áo, ngân sách 4 triệu để tư vấn mẫu phù hợp."],
    summary: "Khách cần máy hút ẩm cho phòng 20 m², ưu tiên chạy êm và hong quần áo. Ngân sách 4 triệu.", needs: ["Phòng 20 m²", "Chạy êm và hong quần áo", "Ngân sách 4 triệu"], nextSteps: ["Đề xuất mẫu phù hợp ngân sách"],
    memory: { customer_memory: { dien_tich_m2: 20, ngan_sach_vnd: 4000000, uu_tien: ["Chạy êm", "Hong quần áo"] }, working_memory: { intent: "Tìm sản phẩm" }, memory_deltas: [], customer_profile: null, past_history: [], retrieved_data: null },
  },
  {
    id: "demo-chat-006", name: "Lê Thu Hà", email: "thuha@example.invalid", phone: "093***3603",
    source: "chat", time: "2026-10-12T08:30:00Z", status: "ended",
    transcript: ["Mình cần máy lọc không khí nhỏ cho phòng làm việc 12 m².", "AirPure Mini trong danh mục mẫu phù hợp phòng nhỏ. Bạn có muốn nhân viên hỗ trợ thông tin giao hàng không?", "Có, gửi mình chi phí giao hàng nhé.", "Mình ghi nhận yêu cầu báo phí giao hàng. Bạn chưa xác nhận đơn hàng trong hội thoại này."],
    summary: "Khách tìm AirPure Mini cho phòng làm việc 12 m²; yêu cầu báo phí giao hàng.", needs: ["Máy lọc nhỏ cho phòng 12 m²"], nextSteps: ["Xác nhận địa chỉ và phí giao hàng"],
    memory: { customer_memory: { dien_tich_m2: 12, san_pham_quan_tam: "AirPure Mini" }, working_memory: { buoc_tiep_theo: "Báo phí vận chuyển" }, memory_deltas: [], customer_profile: null, past_history: [], retrieved_data: { san_pham: "SKU-AP-MINI" } },
  },
  {
    id: "demo-voice-007", name: "Đặng Tuấn Kiệt", email: "tuankiet@example.invalid", phone: "098***7207",
    source: "voice", time: "2026-10-11T02:00:00Z", status: "ended",
    transcript: ["Tôi muốn nhân viên gọi lại vào chiều mai.", "Dạ, em ghi nhận yêu cầu liên hệ lại vào chiều mai. Anh muốn được tư vấn nhóm sản phẩm nào?", "Máy lọc nước cho gia đình.", "Em đã ghi nhận nhu cầu máy lọc nước và khung giờ gọi lại để nhân viên hỗ trợ."],
    summary: "Khách quan tâm máy lọc nước, đề nghị được liên hệ lại vào chiều hôm sau.", needs: ["Máy lọc nước gia đình", "Liên hệ lại buổi chiều"], nextSteps: ["Xác nhận giờ gọi lại cụ thể"],
    memory: { customer_memory: { nhu_cau: "Máy lọc nước gia đình", gio_lien_he: "Buổi chiều" }, working_memory: { buoc_tiep_theo: "Xác nhận thời gian gọi lại" }, memory_deltas: [], customer_profile: null, past_history: [], retrieved_data: null },
  },
  {
    id: "demo-chat-008", name: "Bùi Mai Phương", email: "maiphuong@example.invalid", phone: "097***8408",
    source: "chat", time: "2026-10-10T01:00:00Z", transcript: [], memory: null,
  },
];

const conversations: DemoConversation[] = samples.map(sample => {
  const userId = `demo-user-${sample.email.split("@")[0]}`;
  const item: HistoryItem = {
    id: sample.id, source: sample.source, user_id: userId, user_name: sample.name,
    user_email: sample.email, customer_id: userId, customer_phone: sample.phone,
    status: sample.status ?? "active", turn_number: Math.ceil(sample.transcript.length / 2),
    created_at: sample.time, updated_at: sample.time,
  };
  return { item, detail: {
    ...item, user: { id: userId, name: sample.name, email: sample.email },
    call_brief: sample.summary ? { summary: sample.summary, needs: sample.needs ?? [], objections: sample.objections ?? [], unresolved_issues: sample.nextSteps ?? [] } : null,
    memory: sample.memory ?? null, snapshot_at: sample.memory ? sample.time : null,
    messages: sample.transcript.map((content, index) => ({ id: `${sample.id}-${index}`, role: index % 2 ? "agent" : "user", content, incomplete: sample.interrupted && index === sample.transcript.length - 1 })),
    has_more: false, next_offset: 0,
  } };
});

const normalize = (value: string) => value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d");
const pageSize = 4;
const messagePageSize = 6;

/** Same read-only shape as the future API, with entirely local, immutable fixtures. */
export const salesmanDemo = {
  async list(q: string, source: string, offset = 0, signal?: AbortSignal): Promise<HistoryPage> {
    signal?.throwIfAborted();
    const query = normalize(q.trim());
    const filtered = conversations.filter(({ item }) => (source === "all" || item.source === source)
      && normalize([item.user_name, item.user_email, item.customer_phone, item.id, item.customer_id].join(" ")).includes(query));
    return structuredClone({ items: filtered.slice(offset, offset + pageSize).map(row => row.item), total: filtered.length, has_more: offset + pageSize < filtered.length });
  },
  async get(source: HistorySource, id: string, offset = 0, signal?: AbortSignal): Promise<HistoryDetail> {
    signal?.throwIfAborted();
    const row = conversations.find(row => row.item.id === id && row.item.source === source);
    if (!row) throw new Error("Không tìm thấy hội thoại mẫu. Hãy chọn một hội thoại khác.");
    return structuredClone({ ...row.detail, messages: row.detail.messages.slice(offset, offset + messagePageSize), has_more: offset + messagePageSize < row.detail.messages.length, next_offset: Math.min(offset + messagePageSize, row.detail.messages.length) });
  },
};
