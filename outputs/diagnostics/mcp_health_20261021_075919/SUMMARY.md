# Kiểm tra MCP — 21/10/2026

Backend khởi tạo được 3 MCP server và đăng ký đủ 10 business tool. Tuy nhiên Knowledge MCP không tra cứu được vì thiếu thư viện `pinecone` trong `.venv`.

| Nhóm | Kết quả | Phạm vi đã xác nhận |
|---|---|---|
| Runtime MCP | Đạt | Khởi tạo bằng bootstrap thật; khám phá đủ 10 business tool qua stdio |
| DB: CRM/catalog/inventory/pricing/order status | Đạt | Gọi qua MCP thật, gồm dữ liệu có thật và trường hợp không tìm thấy |
| Tạo/cập nhật đơn | Đạt trong phạm vi kiểm tra | MCP thật kiểm tra guard từ chối; nhánh thành công/idempotency/update dùng DB mock. Chưa kiểm tra ghi đơn thành công vào PostgreSQL thật |
| Knowledge/Pinecone | Lỗi 3/3 truy vấn | Đổi trả, vận chuyển/COD, bảo hành đều trả `knowledge_search_failed: No module named 'pinecone'` |
| Workflow: callback/handoff | Đạt về logic/contract | Gọi qua MCP thật, có kiểm tra dời lịch ngày lễ. Implementation chỉ sinh mã callback/ticket; chưa lưu lịch hoặc gửi yêu cầu cho nhân viên |
| Memory MCP độc lập | Đạt 5/5 thao tác | Ghi profile, behavior, atomic fact, foresight, episode vào thư mục riêng `isolated_memory`; server này không được nạp trong runtime hiện tại |

Tổng hợp: **30/33 kiểm tra đạt; 3 lỗi đều ở Knowledge**. Các kết quả mong đợi như product_not_found/missing_delivery_address được tính đạt khi đúng điều kiện thử nghiệm.

## Chẩn đoán

- `.env`: `KNOWLEDGE_BACKEND=pinecone`, `KNOWLEDGE_RETRIEVAL_MODE=mcp`; có cấu hình key Pinecone. Không hiển thị giá trị key.
- `pinecone>=10,<11` đã khai báo trong `requirements.txt` và `pyproject.toml`, nhưng package chưa được cài trong môi trường Python của backend. Vì import thất bại trước khi truy vấn, chưa xác nhận được quyền truy cập index/namespace Pinecone.
- Cần cài dependency rồi khởi động lại backend và thử lại truy vấn Knowledge. Chưa cài dependency hoặc sửa cấu hình trong lần kiểm tra này.

```powershell
.\.venv\Scripts\python.exe -m pip install "pinecone>=10,<11"
.\scripts\start_api.ps1 -Reload
```

- LangSmith đang bật tracing và báo HTTP 403 Forbidden khi upload. Đây là lỗi quan sát trace riêng; không làm các phép đọc DB trong đợt kiểm tra này thất bại.
- File memory hiện tại không cung cấp `search_archive`; runtime chỉ thêm `search_customer_memory_archive` khi repository hỗ trợ. Vì vậy có 10 business tool là đúng với cấu hình hiện tại. Không đồng nghĩa memory lưu fact/episode bị hỏng.
- PostgreSQL trước/sau đều: **40 sản phẩm, 50 khách hàng, 2 đơn hàng**.
- Không gọi Gemini, không chạy hội thoại/eval, không ghi memory khách hàng thật, không tạo/cập nhật đơn thật, không sửa mã nguồn ứng dụng hoặc `.env`.

## Bằng chứng

- `report.json`: 33 kiểm tra, thời gian và kết quả rút gọn, không lưu dữ liệu riêng của khách hàng.
- `check_mcp.py`: script chẩn đoán có thể chạy lại; không dùng làm benchmark latency.
- `isolated_memory/`: file kiểm tra của khách giả `MCP_DIAGNOSTIC`.
- `report.initial.json`: kết quả thô ban đầu. Test ban đầu kỳ vọng nhầm tool archive tùy chọn; báo cáo cuối sửa kỳ vọng theo điều kiện trong runtime, không chạy lại hoặc che các lỗi Knowledge.
