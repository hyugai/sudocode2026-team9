# Danh sách tool

> Đối chiếu mã nguồn ngày 18/11/2026. Danh mục dưới đây là tool nghiệp vụ được runtime kết nối; quyền dùng còn phụ thuộc kênh và từng lượt. Liên quan: [hệ thống](system-architecture.md), [harness](agent-harness-loop.md), [bộ nhớ](memory-design.md), [quyết định thiết kế](design-decisions.md).

## 1. Tổ chức và quy ước

`connect_tools()` mở **11 MCP tools** từ ba server: Business/DB (8), Knowledge (1), Workflow (2). Runtime có thể gắn thêm một archive tool khi repository hỗ trợ; Voice có thêm tool nội bộ `get_customer_context`.

Tên runtime là tên được đăng ký/gọi. Tên canonical dùng trong trace, `AgentStep`, memory extraction và evaluation. Registry có tool không có nghĩa model được dùng tool đó trong mọi lượt. ASR, perception, CallBrief và persister là dịch vụ của application, không phải tool nghiệp vụ cấp cho model.

## 2. Business MCP — `mcp_db.py`

Các field dưới đây là đầu vào/đầu ra chính, không thay thế schema đầy đủ của server.

| Tool runtime → canonical | Loại | Đầu vào chính | Kết quả / mục đích |
| --- | --- | --- | --- |
| `retrieve_customer_profile` → `crm.get_customer` | Đọc | `phone`, `zalo_id`, `fb_id` tùy chọn | Tra hồ sơ và lịch sử khách; pipeline identity hiện chủ yếu resolve qua phone |
| `search_catalog` → `catalog.search` | Đọc | `query`, `category`, `sku`, `max_price_vnd`, `min_room_area_m2`, `on` tùy chọn | Sản phẩm/biến thể phù hợp và thông tin catalog |
| `check_inventory` → `inventory.check` | Đọc | `sku`; `on` tùy chọn | Tồn kho, số lượng và khả năng bán tại ngày xét |
| `get_pricing_quote` → `pricing.get_quote` | Đọc | `sku`; `qty`, `basket_skus`, identity, `address`, `on` tùy chọn | Giá/khuyến mãi theo điều kiện hiện tại |
| `get_order_quote` → `pricing.quote_order` | Đọc | `lines: [{sku, qty, ...}]`; identity, `address`, `on` tùy chọn | Báo giá toàn giỏ theo từng unit, ưu đãi và tổng `total_vnd` |
| `create_new_order` → `order.create` | Ghi | `customer_phone`; `sku` hoặc `lines`; địa chỉ; payment, giá, promo, ngày và `idempotency_key` tùy chọn theo schema | Kiểm tra lại quote/tồn kho rồi lưu một đơn; trả order ID, tổng tiền, ETA hoặc lỗi |
| `check_order_status` → `order.status` | Đọc | `order_id` hoặc `customer_phone` | Danh sách đơn và trạng thái đã lưu |
| `update_order` → `order.update` | Ghi | `order_id`, `action`; `new_variant_sku`, `reason`, `on` tùy chọn | Đổi/hoàn đơn, phí, chênh lệch, trạng thái hoặc lỗi |

Tạo đơn không tin trực tiếp giá do model đưa: tool kiểm tra quote, số lượng tồn và điều kiện thanh toán. Có `idempotency_key` thì replay đơn phù hợp hoặc trả conflict; không phải mọi tool ghi đều có idempotency bền vững.

`update_order` có các action `exchange_size`, `exchange_product`, `return`, `update_address`. Nhánh `update_address` hiện chỉ cập nhật trạng thái; API tool chưa có field địa chỉ mới, nên không nên mô tả là đã đổi địa chỉ giao hàng đầy đủ.

## 3. Knowledge MCP — `mcp_knowledge.py`

| Tool runtime → canonical | Đầu vào chính | Kết quả / ràng buộc |
| --- | --- | --- |
| `search_policy` → `policy.search` | `query`; `k=3`, `product_sku`, `as_of` tùy chọn | Tra policy, shipping, warranty và quy tắc cửa hàng; trả nguồn/chunk provenance, loại tài liệu internal/hết hiệu lực theo knowledge layer |

Knowledge backend được chọn bằng `KNOWLEDGE_BACKEND` (`chroma` hoặc `pinecone`). Tool này dùng cho chính sách; báo giá hiện tại vẫn lấy từ pricing. `search_knowledge_base` có mapping/schema tương thích trong protocol/Voice, nhưng không được ba MCP server hiện tại đăng ký, nên không tính vào 11 tool đang kết nối.

## 4. Workflow MCP — `mcp_workflow.py`

| Tool runtime → canonical | Đầu vào chính | Kết quả / ràng buộc |
| --- | --- | --- |
| `mcp_schedule_callback` → `schedule.callback` | `customer_phone`, `callback_at`; `note`, `on` tùy chọn | Sinh `callback_id`, điều chỉnh theo giờ mở cửa/ngày nghỉ; trả thời gian cuối cùng và `moved_from` |
| `mcp_escalate_to_human` → `handoff.transfer` | `brief` theo `HandoffBrief` | Validate brief, trả `ticket_id`, `status: queued`, `brief_ok`; thiếu/sai field trả lỗi |

Nếu callback bị dời, câu trả lời phải thông báo thời gian đã điều chỉnh. Hai tool hiện trả kết quả nhưng chưa ghi vào hàng đợi bền vững hay gửi thông báo/chuyển cuộc gọi thực tế; `queued` không chứng minh một nhân viên đã nhận ticket.

## 5. Memory archive và context Voice

| Tool | Đường thực thi | Đầu vào / kết quả |
| --- | --- | --- |
| `search_customer_memory_archive` → `memory.archive_search` | Local tool được gắn khi memory có `search_archive()`; không qua MCP server | Chat: `query`, `section="episodes"`, `day` tùy chọn; đọc chi tiết memory cũ. Customer ID lấy từ runtime, model không tự chọn khách khác |
| `get_customer_context` | Nội bộ Voice dispatcher; không phải MCP tool | Không nhận arguments; refresh memory, dựng lại CallBrief đã mask và trả `mode: read_only` |

Voice chỉ công bố `query` cho archive tool và dùng section mặc định. Archive là dữ kiện lịch sử, không thay current facts hay tool nghiệp vụ. Các module/tool ghi memory khác trong source không được `connect_tools()` nạp cho agent; việc ghi do persister sở hữu.

## 6. Quyền theo kênh và từng lượt

| Nhóm | Chat/file ghi âm | Voice realtime |
| --- | --- | --- |
| Catalog, inventory, pricing, quote giỏ, policy | Allowlist theo intent/transcript/facts; có read prefetch/cache | Chỉ đọc, schema hẹp và kiểm tra allowlist tại backend |
| CRM / order status | Application hydrate hoặc tool theo policy | Không công bố trực tiếp trong Live declarations; context khách qua `get_customer_context` |
| Order create/update, callback, handoff | Mutation executor xử lý nhánh đã xác nhận/đủ dữ liệu; phần còn lại chịu routing của graph | Không công bố và dispatcher chặn |
| Archive | Khi có adapter hỗ trợ và identity hợp lệ | Khi registry có, bind identity ở backend |
| Memory write / sửa instructions / shell | Không cấp cho agent tư vấn | Không cấp cho model Live |

Voice chỉ nhận `REALTIME_TOOLS_MODE=off` hoặc `read_only`. Dispatcher kiểm tra kiểu/field thừa/giới hạn args, bind identity/địa chỉ/ngày nghiệp vụ ở backend, timeout read và mask kết quả gửi model. Evidence giữ bản kết quả thực tế cho persistence. Một function `call_id` đang chạy/đã có kết quả không bị thực thi read lần nữa trong cùng phiên.

## 7. Căn cứ triển khai

- [MCP runtime](../../src/telesale_agent/adapters/mcp/runtime.py), [DB server](../../src/mcp_servers/mcp_db.py), [Knowledge server](../../src/mcp_servers/mcp_knowledge.py), [Workflow server](../../src/mcp_servers/mcp_workflow.py).
- [Canonical protocol](../../src/telesale_agent/application/tools/protocol.py), [tool policy](../../src/telesale_agent/application/conversation/tool_policy.py), [memory archive](../../src/telesale_agent/application/tools/memory_archive.py).
- [Order implementation](../../src/mcp_servers/tools/order.py), [workflow implementation](../../src/mcp_servers/tools/workflow.py), [Voice declarations](../../src/telesale_agent/application/realtime/context.py), [Voice dispatcher](../../src/telesale_agent/application/realtime/tool_dispatch.py).
