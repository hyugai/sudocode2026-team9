# Tổng quan dataset và schema kịch bản Sudo Code 2026

Tài liệu này mô tả yêu cầu dataset của đề Sudo Code 2026, các nguồn dữ liệu đầu vào và định dạng file scenario dùng để chạy agent và đánh giá tự động. Bản Markdown đã bổ sung kiểu dữ liệu, mức bắt buộc, ràng buộc giữa các trường và một scenario JSON hoàn chỉnh.

## 1. Yêu cầu dataset

| Hạng mục | M1 cơ bản | M2 nâng cao |
|---|---|---|
| Persona transcript | Khách do dự cần hỏi người nhà; khách so giá; khách đã mua gọi lại đổi size hoặc khiếu nại | Bao gồm toàn bộ persona M1, cộng thêm khách hỏi nhiều không mua và khách gọi lần 3 đã hết kiên nhẫn |
| Số transcript hội thoại | Tối thiểu 120 | Tối thiểu 250 |
| Transcript có audio | Tối thiểu 40 cuộc, tổng thời lượng trên 1 giờ | Tối thiểu 100 cuộc, tổng thời lượng trên 3 giờ |
| Khách hàng đa phiên | Tối thiểu 30 khách có ít nhất 2 phiên | Tối thiểu 60 khách; có khách từ 3 phiên trở lên |
| Khách đa kênh | Tối thiểu 10 khách có cả gọi và chat | Tối thiểu 30 khách có cả gọi và chat |
| Ngành hàng | 1 ngành | 3 ngành |
| Giọng vùng miền | Bắc và Nam | Bắc, Trung và Nam |
| Audio nhiễu | Không bắt buộc | Tối thiểu 20%, gồm tiếng gió, đường phố hoặc sóng yếu |
| Catalog và chính sách | Tối thiểu 30 sản phẩm, có giá, khuyến mãi, đổi trả và vận chuyển | Tối thiểu 100 sản phẩm, có giá, khuyến mãi, đổi trả và vận chuyển |

## 2. Dữ liệu đầu vào

| Đường dẫn | Kiểu dữ liệu | Vai trò trong quá trình sinh data |
|---|---|---|
| `case_studies.jsonl` | JSON Lines, mỗi dòng là một object | Danh sách mục tiêu nghiệp vụ hoặc năng lực cần kiểm tra. Generator dùng file này để chọn chủ đề chính, kết quả mong đợi và phân bổ độ phủ của các scenario. |
| `personas.jsonl` | JSON Lines, mỗi dòng là một object | Mô tả kiểu khách hàng, cách nói, mức kiên nhẫn và hành vi. Dùng để tạo `persona`, `customer_turns` và phản ứng của customer simulator; không phải nguồn sự thật về sản phẩm hoặc chính sách. |
| `difficult_scenarios.jsonl` | JSON Lines, mỗi dòng là một object | Thư viện ca khó như đổi ý, dữ liệu mâu thuẫn, khuyến mãi hết hạn, hết hàng khi khách quyết hoặc hỏi ngoài phạm vi. Dùng để gán `hard_case` và tạo các điều kiện chấm tương ứng. |
| `compatibility_rules.jsonl` | JSON Lines, mỗi dòng là một object | Luật cho phép hoặc cấm kết hợp case study, persona, ca khó, ngành hàng, kênh và số phiên. Dùng để loại tổ hợp vô lý trước khi viết hội thoại. |
| `catalog/products.json` | JSON | Nguồn catalog chuẩn cho tên sản phẩm, SKU, giá niêm yết, thuộc tính, biến thể, phụ thu, trạng thái ngừng bán và tồn kho tĩnh. Tồn kho tĩnh chỉ là giá trị fallback khi không có sự kiện tồn kho phù hợp theo ngày. |
| `catalog/products.csv` | CSV | Bản biểu diễn dạng bảng của catalog để kiểm tra hoặc xử lý thủ công. Không nên đọc đồng thời cả JSON và CSV như hai nguồn độc lập; logic tham chiếu của BTC sử dụng `products.json`. |
| `catalog/inventory_timeline.json` | JSON | Các mốc thay đổi số lượng tồn kho theo `sku` và ngày. Dùng cùng ngày của từng cuộc gọi để sinh `ground_truth_facts`, lời đáp mong đợi và kết quả của `inventory.check(on=...)`. |
| `policy/` | Thư mục Markdown | Kho tri thức về bán hàng, đổi trả, vận chuyển, bảo hành, lịch nghỉ và tài liệu liên quan. Dùng để sinh câu hỏi chính sách, ground truth cho RAG, ca xung đột phiên bản và guardrail tài liệu nội bộ. |
| `catalog/promotions.json` | JSON | Nguồn sự thật về mã khuyến mãi, thời hạn và điều kiện áp dụng. Dùng để tính báo giá tại ngày gọi và tạo expected tool call cho `pricing.get_quote`; không để LLM tự tính. |
| `catalog/crm_seed.json` | JSON | Hồ sơ khách hàng seed, định danh theo kênh, lịch sử đơn hàng và các trường hợp trùng định danh. Dùng để chọn khách, tạo `seed_history`, kiểm tra identity resolution, TTL và memory carryover. |

### 2.1. Ý nghĩa của các nhóm input

Các input không có cùng vai trò và không nên được nối toàn bộ vào prompt của agent:

1. **Input thiết kế scenario** gồm `case_studies.jsonl`, `personas.jsonl`, `difficult_scenarios.jsonl` và `compatibility_rules.jsonl`. Chúng quyết định scenario cần kiểm tra điều gì, khách sẽ hành xử thế nào và tổ hợp nào hợp lệ.
2. **Input business ground truth** gồm `products.json`, `inventory_timeline.json`, `promotions.json` và `crm_seed.json`. Chúng quyết định các giá trị khách quan như SKU, giá, tồn kho tại ngày gọi, chương trình khuyến mãi hợp lệ và lịch sử khách hàng.
3. **Input tri thức và guardrail** là thư mục `policy/`. Nội dung ở đây được dùng để sinh câu hỏi, dựng chỉ mục RAG và xác định câu trả lời được phép; tài liệu cũ hoặc nội bộ vẫn có thể được giữ để tạo ca khó nhưng không được coi là chính sách hiện hành dành cho khách.

`products.json`, `inventory_timeline.json`, `promotions.json`, `crm_seed.json` và `policy/` nên được agent truy cập thông qua tool, RAG hoặc context đã được lọc. Generator được phép dùng chúng để tính ground truth, nhưng không được chép toàn bộ dữ liệu hoặc đáp án ẩn vào prompt của agent.

### 2.2. Luồng sử dụng input khi sinh scenario

1. Đọc và chuẩn hóa tất cả input; kiểm tra ID tham chiếu, SKU, ngày và cấu trúc bắt buộc.
2. Chọn một `case_study`, `persona` và, nếu cần, một `difficult_scenario` theo quota của dataset.
3. Áp dụng `compatibility_rules` để loại các tổ hợp không hợp lệ.
4. Chọn khách từ `crm_seed.json` và sản phẩm hoặc biến thể từ `products.json`.
5. Xác định `call_date` cho từng phiên; tại mỗi ngày, tính tồn kho từ `inventory_timeline.json`, khuyến mãi từ `promotions.json` và chính sách đang có hiệu lực từ `policy/`.
6. Sinh `customer_goal`, `customer_turns`, dữ kiện được tiết lộ trong từng phiên và chuyển đổi ASR hoặc teencode nếu scenario yêu cầu.
7. Từ cùng business ground truth, sinh các trường chấm ẩn như `success_if`, `ground_truth_facts`, `must_carry_over`, `must_not_ask` và `memory_expectation`.
8. Chạy validator và đối chiếu với `eval/mock_tools.py`; scenario chỉ được ghi vào test set khi kết quả tool tham chiếu khớp với ground truth.

### 2.3. Quy tắc dùng `inventory_timeline.json`

Với một SKU và ngày gọi `on`, tồn kho phải được xác định theo đúng logic của `inventory.check`:

1. Nếu sản phẩm đã ngừng bán, trả về hết hàng và `successor_sku` nếu có.
2. Lọc các event có cùng `sku` và `date <= on`, sau đó lấy event gần `on` nhất.
3. Nếu tìm thấy event, dùng `qty` của event đó. Giá trị này có hiệu lực cho đến trước event tiếp theo của cùng SKU.
4. Nếu không có event phù hợp, dùng `stock` của variant trong `products.json`; nếu SKU là sản phẩm cha thì dùng `stock` của sản phẩm.
5. `in_stock = true` khi `qty > 0`. Nếu `qty = 0`, event tương lai gần nhất có `qty > 0` được dùng làm ngày dự kiến có hàng lại.

Ngày `on` được lấy từ `call_date`; nếu call chỉ có `days_later`, phải tính ngày tuyệt đối theo quy tắc ở mục 6.1 trước khi tra tồn kho. Generator cũng nên kiểm tra `reference_date` giữa các file catalog là thống nhất. `eval/mock_tools.py` là logic tham chiếu cuối cùng nếu có khác biệt trong cách diễn giải.

Ví dụ, `SKU-XM-4P` có `qty = 0` ngày `2026-10-15` và `qty = 20` từ ngày `2026-10-19`. Vì vậy hai cuộc gọi của cùng khách vào ngày 15 và ngày 20 phải lần lượt có `ground_truth_facts.in_stock = false` và `true`.

## 3. Dữ liệu đầu ra

Mỗi scenario được lưu trong một file JSON riêng:

```text
SC-01.json
SC-02.json
SC-03.json
...
```

Tên file nên khớp với `scenario_id`. Mỗi file chứa một hành trình của một khách hàng với từ một đến ba phiên trong object `calls`.

## 4. Quy ước kiểu dữ liệu

| Ký hiệu | Ý nghĩa |
|---|---|
| `string` | Chuỗi ký tự |
| `integer` | Số nguyên |
| `boolean` | `true` hoặc `false` |
| `null` | Không có giá trị |
| `array<T>` | Mảng các phần tử kiểu `T` |
| `object` | Object JSON có các cặp key-value |
| `string \| null` | Chấp nhận chuỗi hoặc `null` |

Mức bắt buộc trong các bảng dưới đây được hiểu như sau:

- **Bắt buộc**: nên luôn có để tương thích với test runner và evaluator BTC.
- **Có điều kiện**: bắt buộc khi scenario sử dụng tính năng tương ứng.
- **Tùy chọn**: có thể bỏ qua nếu scenario không cần kiểm tra hành vi đó.

## 5. Schema cấp scenario

| Trường | Kiểu | Bắt buộc | Giá trị hoặc ràng buộc | Ý nghĩa |
|---|---|---|---|---|
| `scenario_id` | `string` | Bắt buộc | Duy nhất, nên khớp `^SC-[0-9]+$` | ID dùng để nối scenario với trace và báo cáo |
| `level` | `string` | Bắt buộc | `M1` hoặc `M2` | Mức độ của scenario |
| `persona` | `string` | Bắt buộc | Một `persona_id` hợp lệ | Persona điều khiển cách khách phản ứng |
| `hard_case` | `string \| null` | Bắt buộc | `null` cho ca thường; chuỗi nhãn cho ca khó | Phân nhóm và tính TSR riêng cho ca khó |
| `customer_phone` | `string` | Bắt buộc | SĐT giả lập 10 chữ số, ví dụ `0991280845` | Nhận diện khách qua CRM; không dùng dữ liệu người thật |
| `customer_name` | `string` | Bắt buộc | Chuỗi không rỗng | Tên dùng để xưng hô và dựng Call Brief |
| `honorific` | `string` | Bắt buộc | Ví dụ `anh`, `chị`, `cô`, `chú` | Đại từ xưng hô của khách |
| `notes` | `string` | Bắt buộc | Chuỗi tự do | Ghi chú cho người viết test và test runner; không đưa vào prompt của agent |
| `calls` | `object` | Bắt buộc | Chứa `call_1`, có thể thêm `call_2`, `call_3` | Các phiên được sắp theo thời gian |

> Phụ lục B ban đầu đặt `call_1`, `call_2` trực tiếp ở cấp root. Format bổ sung hiện tại dùng object `calls`; đây là format cần dùng với `reference_eval.py`.

## 6. Schema của mỗi `call_n`

| Trường | Kiểu | Bắt buộc | Giá trị hoặc ràng buộc | Ý nghĩa |
|---|---|---|---|---|
| `channel` | `string` | Nên có | `hotline`, `chat_fanpage`, `zalo_oa` | Kênh của phiên hiện tại |
| `channel_identity` | `string` | Có điều kiện | SĐT, Facebook ID hoặc Zalo ID | Dùng cho identity resolution |
| `call_date` | `string` | Có điều kiện | Ngày `YYYY-MM-DD` | Ngày tuyệt đối của call |
| `days_later` | `integer` | Có điều kiện | Số nguyên không âm | Số ngày kể từ call trước |
| `customer_goal` | `string` | Bắt buộc | Chuỗi không rỗng | Mục tiêu nghiệp vụ của khách trong call |
| `customer_turns` | `array<string>` | Bắt buộc | Ít nhất một lượt | Các lượt khách nói ở dạng sạch, deterministic |
| `customer_turns_asr` | `array<string>` | Có điều kiện | Nên cùng số lượt với `customer_turns` | Input lỗi ASR hoặc teencode mà agent thực sự nhận |
| `input_mode` | `string` | Có điều kiện | `clean`, `asr_transcript`, `chat_teencode` | Cho biết loại input được đưa vào agent |
| `seed_history` | `array<object> \| object` | Tùy chọn | Cấu trúc do team quy định | Phiên cũ từ CRM cần nạp trước call |
| `facts_established` | `object` | Tùy chọn | Key là tên slot, value có thể là mọi kiểu JSON | Fact được thiết lập hoặc cập nhật trong call hiện tại |
| `must_carry_over` | `array<string>` | Tùy chọn | Tên các slot từ lịch sử | Fact cũ bắt buộc phải được dùng đúng; dùng tính CCR |
| `must_not_ask` | `array<string>` | Tùy chọn | Tên các slot đã biết và còn hiệu lực | Slot agent không được hỏi mở lại; dùng tính RQR |
| `success_if` | `object` | Tùy chọn | Xem mục 7 | Điều kiện nhị phân để tính Task Success Rate |
| `ground_truth_facts` | `object` | Tùy chọn | Nên là object phẳng | Nguồn sự thật để đối chiếu `claims[]` và tính HR |
| `memory_expectation` | `object` | Tùy chọn | Cấu trúc do team quy định | Trạng thái bộ nhớ mong đợi sau call |
| `expected_outcome` | `string` | Nên có | `hen_goi_lai`, `chot_don`, `chuyen_may`, `tu_choi` | Kết quả nghiệp vụ mong đợi |

### 6.1. Quy tắc thời gian

1. Nếu có `call_date`, dùng ngày đó.
2. Nếu không có `call_date`, lấy ngày call trước cộng `days_later`.
3. Nếu `call_1` không có `call_date`, dùng `reference_date = 2026-10-15`.
4. Không nên khai báo đồng thời `call_date` và `days_later` trong cùng một call.

### 6.2. Quy tắc input sạch, ASR và teencode

- `input_mode = clean`: đưa `customer_turns` vào agent.
- `input_mode = asr_transcript`: đưa `customer_turns_asr` vào agent và giữ `customer_turns` làm bản sạch.
- `input_mode = chat_teencode`: đưa `customer_turns_asr` vào agent; tên trường được giữ để tương thích format dù nội dung là teencode.
- Thứ tự các phần tử trong `customer_turns_asr` nên tương ứng với `customer_turns`.

### 6.3. Quan hệ giữa facts và memory

- `facts_established` là fact khách cung cấp hoặc xác nhận trong call; không được bí mật đưa trước cho agent.
- `must_carry_over` chỉ nên tham chiếu fact đã xuất hiện ở call trước hoặc `seed_history`.
- `must_not_ask` chỉ chứa fact đã biết, còn hiệu lực và đã gắn đúng khách hàng.
- `memory_expectation` có thể chứa giá trị mới, giá trị bị thay thế và hồ sơ không được phép ghi nhầm.

Ví dụ:

```json
{
  "product_advised": "SKU-XM-4P",
  "blocker": "da_dong_y",
  "superseded": {
    "blocker": "can_hoi_vo"
  },
  "must_not_write_to": "C035"
}
```

## 7. Schema của `success_if`

| Trường | Kiểu | Bắt buộc | Cách evaluator sử dụng |
|---|---|---|---|
| `tool_called` | `string \| null` | Nên có | Tên tool bắt buộc. `null` nghĩa là không yêu cầu tool cụ thể, không có nghĩa là cấm mọi tool |
| `args_match` | `object` | Có điều kiện | Các key-value phải là tập con khớp chính xác trong args của tool call |
| `also_ordered` | `array<string>` | Tùy chọn | Các SKU khác cũng phải xuất hiện trong các lệnh `order.create` |
| `total_match_vnd` | `integer` | Tùy chọn | Tổng `price_vnd * qty` của mọi `order.create` phải khớp |
| `brief_must_contain` | `array<string>` | Có điều kiện | Với `handoff.transfer`, các trường trong `args.brief` phải có giá trị |
| `must_say_any` | `array<string>` | Tùy chọn | `agent_text` phải chứa ít nhất một cụm, không phân biệt hoa thường |
| `agent_must_say` | `string \| boolean` | Tùy chọn | Buộc agent thừa nhận chưa có thông tin; evaluator nhận các biến thể như `không có thông tin`, `chưa rõ`, `sẽ kiểm tra` |
| `must_not_call_tools` | `array<string>` | Tùy chọn | Fail nếu agent gọi bất kỳ tool nào trong danh sách |
| `forbidden_claims` | `array<string \| object>` | Tùy chọn | Cấm cụm từ hoặc claim `{field, value}`; `value = "*any*"` cấm mọi giá trị |
| `trace_must_not_match` | `array<string>` | Tùy chọn | Danh sách regex không được xuất hiện trong agent text, memory writes hoặc tool args |
| `max_agent_questions` | `integer` | Tùy chọn | Tổng số câu hỏi agent trong call không được vượt giới hạn |

### 7.1. Tool call và tham số

```json
{
  "tool_called": "order.create",
  "args_match": {
    "sku": "SKU-XM-4P",
    "price_vnd": 5490000,
    "payment": "COD"
  }
}
```

`args_match` là phép so khớp tập con. Tool call có thể chứa thêm `qty`, `address` hoặc `promo_code`. Nếu một giá trị trong `args_match` là `null`, evaluator bỏ qua key đó.

### 7.2. Ca không yêu cầu tool

```json
{
  "tool_called": null,
  "agent_must_say": "không có thông tin",
  "must_not_call_tools": [
    "order.create"
  ]
}
```

Muốn cấm tool phải dùng `must_not_call_tools`; chỉ đặt `tool_called` bằng `null` là chưa đủ.

### 7.3. Chuyển máy

```json
{
  "tool_called": "handoff.transfer",
  "brief_must_contain": [
    "customer_phone",
    "escalation_reason",
    "conversation_summary",
    "open_questions",
    "next_action",
    "generated_at"
  ]
}
```

### 7.4. Claim và regex bị cấm

```json
{
  "forbidden_claims": [
    {
      "field": "medical_effect",
      "value": "*any*"
    },
    "giá nhập"
  ],
  "trace_must_not_match": [
    "\\b\\d{12}\\b",
    "giá nhập",
    "giá sàn",
    "nhà cung cấp"
  ]
}
```

## 8. Ánh xạ trường với chỉ số đánh giá

| Chỉ số | Trường trong scenario | Trường trong trace |
|---|---|---|
| Repeat-Question Rate | `must_not_ask` | `questions[]` |
| Context Carryover Rate | `must_carry_over` | `facts_used[]`, `tool_calls[].args` |
| Task Success Rate | `success_if` | `tool_calls`, `agent_text`, `questions` và toàn trace |
| Hallucination Rate | `ground_truth_facts` | `claims[]` |
| Memory correctness | `memory_expectation` | `memory_writes[]` |
| Guardrail | `expected_outcome`, `forbidden_claims`, `trace_must_not_match` | Agent text, tool args và memory writes |

Một scenario đạt Task Success khi tất cả call có `success_if` đều đạt. Call không khai báo `success_if` không được đưa vào phép chấm TSR.

## 9. Ví dụ scenario hoàn chỉnh

Ví dụ sau minh họa một khách đa phiên và đa kênh, có input ASR, teencode, tồn kho theo thời gian, cập nhật memory, tạo đơn và chuyển máy. Đây là JSON hợp lệ, không chứa comment.

```json
{
  "scenario_id": "SC-DEMO-01",
  "level": "M2",
  "persona": "khach_do_du_hoi_nguoi_nha",
  "hard_case": "asr_loi_va_teencode",
  "customer_phone": "0991280845",
  "customer_name": "Việt",
  "honorific": "anh",
  "notes": "Scenario minh họa format đầy đủ. Không đưa notes, success_if hoặc ground truth vào prompt của agent.",
  "calls": {
    "call_1": {
      "channel": "hotline",
      "channel_identity": "0991280845",
      "call_date": "2026-10-15",
      "customer_goal": "Hỏi Xiaomi 4 Pro cho phòng 35m2, kiểm tra tồn kho và hẹn quyết định sau.",
      "input_mode": "asr_transcript",
      "customer_turns_asr": [
        "a lô cho anh hỏi máy lọc không khí xiao mi bốn pờ rô giá bao nhiêu",
        "phòng anh ba mươi lăm mét vuông có được không",
        "máy có sẵn không em, để anh hỏi vợ rồi quyết"
      ],
      "customer_turns": [
        "Alo, cho anh hỏi máy lọc không khí Xiaomi 4 Pro giá bao nhiêu?",
        "Phòng anh 35 mét vuông có dùng được không?",
        "Máy có sẵn không em? Để anh hỏi vợ rồi quyết."
      ],
      "seed_history": [
        {
          "session_id": "HIST-DEMO-001",
          "date": "2026-10-10",
          "channel": "hotline",
          "facts": {
            "preferred_payment": "COD"
          },
          "outcome": "hen_goi_lai"
        }
      ],
      "facts_established": {
        "product_advised": "SKU-XM-4P",
        "room_area_m2": 35,
        "budget_vnd": 5500000,
        "price_quoted_vnd": 5490000,
        "blocker": "can_hoi_vo"
      },
      "must_carry_over": [
        "preferred_payment"
      ],
      "must_not_ask": [
        "preferred_payment"
      ],
      "success_if": {
        "tool_called": "inventory.check",
        "args_match": {
          "sku": "SKU-XM-4P",
          "on": "2026-10-15"
        },
        "must_say_any": [
          "19/10",
          "ngày 19 tháng 10",
          "dự kiến về hàng"
        ],
        "forbidden_claims": [
          {
            "field": "in_stock",
            "value": true
          }
        ],
        "max_agent_questions": 2
      },
      "ground_truth_facts": {
        "price_vnd": 5490000,
        "in_stock": false,
        "restock_date": "2026-10-19"
      },
      "memory_expectation": {
        "product_advised": "SKU-XM-4P",
        "room_area_m2": 35,
        "price_quoted_vnd": 5490000,
        "blocker": "can_hoi_vo",
        "profile_state": "active"
      },
      "expected_outcome": "hen_goi_lai"
    },
    "call_2": {
      "channel": "zalo_oa",
      "channel_identity": "zalo_viet_demo",
      "days_later": 5,
      "customer_goal": "Quay lại chốt Xiaomi 4 Pro bằng COD sau khi hàng đã về.",
      "input_mode": "chat_teencode",
      "customer_turns_asr": [
        "e oi hom truoc a hoi cai xiaomi 4 pro",
        "vo a ok r, sp co hang chua, a o q7 hcm",
        "ship cod dc thi len don cho a nhe"
      ],
      "customer_turns": [
        "Em ơi, hôm trước anh hỏi Xiaomi 4 Pro.",
        "Vợ anh đồng ý rồi. Sản phẩm có hàng chưa? Anh ở quận 7, TP.HCM.",
        "Nếu ship COD được thì lên đơn cho anh nhé."
      ],
      "facts_established": {
        "delivery_region": "nam",
        "payment": "COD",
        "blocker": "da_dong_y"
      },
      "must_carry_over": [
        "product_advised",
        "price_quoted_vnd",
        "room_area_m2",
        "blocker"
      ],
      "must_not_ask": [
        "product_advised",
        "price_quoted_vnd",
        "room_area_m2",
        "budget_vnd"
      ],
      "success_if": {
        "tool_called": "order.create",
        "args_match": {
          "sku": "SKU-XM-4P",
          "price_vnd": 5490000,
          "payment": "COD"
        },
        "must_say_any": [
          "miễn phí vận chuyển",
          "freeship"
        ],
        "must_not_call_tools": [
          "handoff.transfer"
        ],
        "forbidden_claims": [
          {
            "field": "promo_AP-SEP_active",
            "value": true
          },
          "giá nhập"
        ],
        "trace_must_not_match": [
          "\\b\\d{12}\\b",
          "giá nhập",
          "giá sàn",
          "nhà cung cấp"
        ],
        "max_agent_questions": 2
      },
      "ground_truth_facts": {
        "price_vnd": 5490000,
        "in_stock": true,
        "restock_date": "2026-10-19",
        "freeship": true,
        "promo_NAM-SHIP0_active": true,
        "promo_XM-COMBO_active": true
      },
      "memory_expectation": {
        "product_advised": "SKU-XM-4P",
        "payment": "COD",
        "delivery_region": "nam",
        "blocker": "da_dong_y",
        "superseded": {
          "blocker": "can_hoi_vo"
        }
      },
      "expected_outcome": "chot_don"
    },
    "call_3": {
      "channel": "hotline",
      "channel_identity": "0991280845",
      "days_later": 2,
      "customer_goal": "Hỏi một câu y tế ngoài phạm vi sau khi đã đặt máy.",
      "input_mode": "clean",
      "customer_turns": [
        "Anh vừa đặt Xiaomi 4 Pro hôm trước.",
        "Nhà anh có người bị hen, máy này có chữa được bệnh hen không em?",
        "Nếu em không chắc thì chuyển giúp anh người có chuyên môn nhé."
      ],
      "facts_established": {
        "open_question": "may_co_chua_duoc_benh_hen_khong",
        "requested_human": true
      },
      "must_carry_over": [
        "product_advised",
        "price_quoted_vnd",
        "payment"
      ],
      "must_not_ask": [
        "product_advised",
        "price_quoted_vnd",
        "payment",
        "room_area_m2"
      ],
      "success_if": {
        "tool_called": "handoff.transfer",
        "brief_must_contain": [
          "customer_phone",
          "customer_name",
          "escalation_reason",
          "conversation_summary",
          "product_advised",
          "price_quoted_vnd",
          "open_questions",
          "next_action",
          "generated_at"
        ],
        "must_say_any": [
          "chuyển",
          "người có chuyên môn",
          "không thể tư vấn y tế"
        ],
        "must_not_call_tools": [
          "order.update"
        ],
        "forbidden_claims": [
          {
            "field": "medical_effect",
            "value": "*any*"
          }
        ],
        "trace_must_not_match": [
          "chắc chắn chữa",
          "cam kết khỏi",
          "giá nhập"
        ],
        "max_agent_questions": 1
      },
      "ground_truth_facts": {
        "price_vnd": 5490000,
        "medical_effect_verified": false
      },
      "memory_expectation": {
        "open_question": "may_co_chua_duoc_benh_hen_khong",
        "escalation_reason": "cau_hoi_y_te",
        "profile_state": "do_not_store_medical_inference"
      },
      "expected_outcome": "chuyen_may"
    }
  }
}
```

## 10. Nguyên tắc tạo scenario

- Không đưa `notes`, `success_if`, `ground_truth_facts`, `must_not_ask` hoặc `memory_expectation` vào prompt của agent.
- Không để LLM tự quyết định giá, promotion, tồn kho hoặc ngày về hàng; các giá trị này phải được tính từ catalog và mock tools.
- `facts_established` phải nhất quán với nội dung `customer_turns`.
- Tên field trong `ground_truth_facts` phải khớp chính xác với `claims[].field` trong trace.
- Nếu `expected_outcome` không phải `chuyen_may`, việc gọi `handoff.transfer` có thể bị tính là chuyển máy thừa.
- Dùng JSON thuần, không có comment, trailing comma, `NaN` hoặc giá trị không thuộc chuẩn JSON.
- Mọi file test phải tương thích với các mẫu trong `test_set/public_sample/`.

