# Đặc tả bốn file output của pipeline sinh dataset hội thoại

Tài liệu này mô tả chi tiết bốn file output:

1. `conversation_scripts.jsonl`
2. `sessions.jsonl`
3. `messages.jsonl`
4. `session_products.jsonl`

Nội dung được đối chiếu với `generate_conversation_dataset.ipynb` và snapshot hiện có trong thư mục `output`.

## 1. Quy ước chung

### 1.1. Định dạng JSONL

Mỗi dòng trong file JSONL là một JSON object độc lập:

```jsonl
{"session_id":"SES_000001_01","user_id":"USR_000001","channel":"voice"}
{"session_id":"SES_000002_01","user_id":"USR_000002","channel":"voice"}
```

Không bọc toàn bộ file bằng `[]` và không đặt dấu phẩy giữa các dòng.

Các ví dụ được trình bày nhiều dòng để dễ đọc. Khi ghi vào JSONL, mỗi object phải nằm trên đúng một dòng.

### 1.2. Phân biệt hai loại miền giá trị

- **Miền được generator cho phép**: enum, mẫu ID và giới hạn được notebook khai báo hoặc kiểm tra.
- **Giá trị đang xuất hiện**: giá trị quan sát được trong bốn file hiện tại. Lần chạy mới có thể sinh các giá trị khác nhưng vẫn nằm trong miền được phép.

### 1.3. Vai trò của bốn file

| File | Vai trò |
|---|---|
| `conversation_scripts.jsonl` | Bản lồng đầy đủ của một customer journey, chứa user, sessions, sản phẩm và messages |
| `sessions.jsonl` | Bảng chuẩn hóa metadata của từng phiên; không chứa messages hoặc sản phẩm |
| `messages.jsonl` | Bảng chuẩn hóa từng lượt thoại/tin nhắn |
| `session_products.jsonl` | Bảng nối giữa session và sản phẩm trong `catalogs.jsonl` |

Quan hệ chính:

```text
conversation_scripts.user.user_id
                │
                └── sessions.user_id
                         │
                         ├── messages.session_id
                         │
                         └── session_products.session_id
                                      │
                                      └── product_id = catalogs.sku
```

Snapshot hiện tại có:

| File | Số dòng |
|---|---:|
| `conversation_scripts.jsonl` | 6 |
| `sessions.jsonl` | 12 |
| `messages.jsonl` | 104 |
| `session_products.jsonl` | 12 |

## 2. `conversation_scripts.jsonl`

### 2.1. Mục đích

Mỗi dòng là một hành trình hội thoại hoàn chỉnh của một khách hàng. File này phù hợp khi cần:

- Đọc trọn vẹn một kịch bản.
- Đưa toàn bộ journey vào LLM hoặc pipeline đánh giá.
- Kiểm tra tính nhất quán qua nhiều phiên và nhiều kênh.
- Truy vết policy và promotion đã dùng để sinh dữ liệu.

### 2.2. Cấu trúc cấp cao

| Trường | Kiểu | Bắt buộc | Miền/ý nghĩa | Giá trị hiện có |
|---|---|---:|---|---|
| `script_id` | string | Có | Khóa script, mẫu `SCRIPT_NNNNNN` | `SCRIPT_000001`–`SCRIPT_000006` |
| `scenario_group_id` | string enum | Có | ID nhóm kịch bản | 3 trong 11 nhóm được phép |
| `is_multi_session` | boolean | Có | `true` khi journey có từ 2 session trở lên, tính trên mọi kênh | `true`, `false` |
| `is_multi_channel` | boolean | Có | `true` khi journey có cả `voice` và `messaging` | `true`, `false` |
| `user` | object | Có | Hồ sơ người dùng của script | Một user/script |
| `sessions` | array[object] | Có | Danh sách session đã lồng cả sản phẩm và message | 1, 3 hoặc 5 session/script trong snapshot |
| `source_policy_ids` | array[string] | Có | Các khóa tham chiếu `policies.policy_id` được dùng làm grounding | Nhiều policy/script |
| `source_promotion_ids` | array[string] | Có | Các khóa tham chiếu `promotions.promotion_id` gắn với sản phẩm được chọn | 1–2 promotion/script trong snapshot |

`difficulty` và `openai_response_id` không còn là trường của `conversation_scripts.jsonl`. Độ khó vẫn tồn tại trong kế hoạch nội bộ của generator; ID phản hồi OpenAI vẫn có thể được giữ trong `raw_journeys.jsonl` để debug và audit.

### 2.3. Miền `scenario_group_id`

Generator hiện cho phép 11 nhóm:

| Giá trị | Độ khó | Ý nghĩa |
|---|---|---|
| `hoi_va_chot_mua` | `thong_thuong` | Hỏi thông tin rồi chốt mua |
| `hoi_nhung_khong_mua` | `thong_thuong` | Hỏi nhưng không chốt mua |
| `do_du_hoi_nguoi_nha` | `trung_binh` | Do dự và cần hỏi người nhà |
| `so_sanh_gia` | `trung_binh` | So sánh giá và tính năng |
| `doi_tra_hoac_khieu_nai` | `trung_binh` | Đổi trả hoặc khiếu nại |
| `hoi_nhieu_khong_mua` | `trung_binh` | Hỏi nhiều nhưng không mua |
| `lan_ba_mat_kien_nhan` | `trung_binh` | Liên hệ lần ba và mất kiên nhẫn |
| `doi_y_giua_chung` | `kho` | Đổi ý giữa chừng |
| `mau_thuan_voi_phien_truoc` | `kho` | Thông tin mâu thuẫn với phiên trước |
| `doi_khuyen_mai_het_han` | `kho` | Yêu cầu áp dụng khuyến mãi cũ/hết hạn |
| `hoi_ngoai_tai_lieu` | `kho` | Hỏi thông tin không có trong nguồn |

Snapshot hiện tại mới có `hoi_va_chot_mua`, `doi_tra_hoac_khieu_nai` và `hoi_ngoai_tai_lieu`.

### 2.4. Object `user`

| Trường | Kiểu | Bắt buộc | Miền/ý nghĩa |
|---|---|---:|---|
| `user_id` | string | Có | Mẫu `USR_NNNNNN`; duy nhất trong một lần chạy |
| `name` | string | Có | Tên người dùng đầu vào hoặc tên do generator sinh |
| `phone` | string | Có | Số masked, generator hiện dùng mẫu `09xxNNNNNN` |
| `region` | string enum | Có | `Bắc`, `Trung`, `Nam` |
| `persona` | string | Có | Mô tả chân dung và hành vi của khách |
| `profile` | object | Có | Nhu cầu, ưu tiên, ngân sách và dữ kiện đã xác minh |

Object `profile`:

| Trường | Kiểu | Bắt buộc | Miền/ý nghĩa |
|---|---|---:|---|
| `needs` | array[string] | Có | Các nhu cầu của khách; chuỗi tự do |
| `preferences` | array[string] | Có | Kênh, cách thanh toán hoặc cách tư vấn ưa thích |
| `budget_note` | string | Có | Ghi chú ngân sách; chuỗi tự do |
| `verified_facts` | array[string] | Có | Dữ kiện đã xác minh, không nên chứa suy đoán |

### 2.5. Object `sessions[]` bên trong script

Mỗi phần tử có toàn bộ trường của một record trong `sessions.jsonl` và thêm `product_ids`, `messages`:

| Trường | Kiểu | Bắt buộc | Miền/ý nghĩa |
|---|---|---:|---|
| `session_id` | string | Có | Mẫu `SES_NNNNNN_NN` |
| `user_id` | string | Có | Phải bằng `user.user_id` của script |
| `channel` | string enum | Có | `voice`, `messaging` |
| `platform` | string enum | Có | `phone`, `zalo`, `facebook_messenger`, `website_chat` |
| `timestamp` | string datetime | Có | ISO 8601 có timezone, ví dụ `2026-09-20T09:00:00+07:00` |
| `summary` | string | Có | Tóm tắt nội dung và tiến triển của phiên |
| `outcome` | string enum | Có | Một trong sáu outcome ở mục 2.6 |
| `product_ids` | array[string] | Có | Các phần tử là `catalogs.sku`; đã loại trùng và sắp xếp |
| `messages` | array[object] | Có | Danh sách message của phiên theo thứ tự `sequence_no` |

Các kết hợp channel/platform được generator tạo:

| `channel` | `platform` hợp lệ trong generator | `message.type` bắt buộc |
|---|---|---|
| `voice` | `phone` | `voice` |
| `messaging` | `zalo`, `facebook_messenger`, `website_chat` | `text` |

Snapshot hiện chưa có `website_chat`, nhưng đây vẫn là giá trị được schema cho phép.

### 2.6. Miền `outcome`

| Giá trị | Ý nghĩa đề xuất |
|---|---|
| `ongoing` | Hành trình chưa kết thúc, còn bước xử lý tiếp theo |
| `callback_scheduled` | Đã hẹn gọi/liên hệ lại |
| `closed_won` | Khách đã đồng ý và hành trình kết thúc thành công |
| `rejected` | Khách từ chối hoặc không tiếp tục |
| `resolved` | Vấn đề hỗ trợ đã được giải quyết |
| `escalated` | Đã hoặc cần chuyển cấp/bộ phận có thẩm quyền |

Snapshot hiện tại có `ongoing`, `callback_scheduled`, `escalated`. Các giá trị còn lại hợp lệ nhưng chưa xuất hiện.

### 2.7. Object `messages[]` bên trong session

| Trường | Kiểu | Bắt buộc | Miền/ý nghĩa |
|---|---|---:|---|
| `message_id` | string | Có | Mẫu `MSG_NNNNNN_NN_NNN` |
| `session_id` | string | Có | Phải bằng `session_id` của session cha |
| `sender` | string enum | Có | `customer`, `agent` |
| `type` | string enum | Có | `voice`, `text`; phải khớp channel |
| `text` | string | Có | Nội dung không rỗng |
| `sequence_no` | integer | Có | Bắt đầu từ 1, tăng liên tục trong session |

Generator yêu cầu session bắt đầu bằng `customer`, sau đó `customer` và `agent` luân phiên. Cấu hình hiện tại cho phép 8–14 message/session; snapshot hiện có 8 hoặc 10.

### 2.8. Ví dụ trực quan

Ví dụ dưới đây được rút gọn còn một session và hai message. Record thật do generator sinh phải tuân thủ giới hạn 8–14 message/session.

```json
{
  "script_id": "SCRIPT_000001",
  "scenario_group_id": "hoi_va_chot_mua",
  "is_multi_session": false,
  "is_multi_channel": false,
  "user": {
    "user_id": "USR_000001",
    "name": "Nguyễn Minh An",
    "phone": "09xx000001",
    "region": "Bắc",
    "persona": "Khách gia đình cần nồi cơm điện dễ sử dụng.",
    "profile": {
      "needs": [
        "Tìm nồi cơm điện dung tích 1.8 lít"
      ],
      "preferences": [
        "Muốn được báo giá rõ ràng"
      ],
      "budget_note": "Ngân sách từ 600.000 đến 1.000.000 VND.",
      "verified_facts": [
        "Khách quan tâm nhóm Nồi cơm điện"
      ]
    }
  },
  "sessions": [
    {
      "session_id": "SES_000001_01",
      "user_id": "USR_000001",
      "channel": "voice",
      "platform": "phone",
      "timestamp": "2026-09-20T09:00:00+07:00",
      "summary": "Khách hỏi thông tin và giá nồi cơm điện.",
      "outcome": "callback_scheduled",
      "product_ids": [
        "delites-ncg1805"
      ],
      "messages": [
        {
          "message_id": "MSG_000001_01_001",
          "session_id": "SES_000001_01",
          "sender": "customer",
          "type": "voice",
          "text": "Tôi muốn hỏi về nồi cơm Delites NCG1805.",
          "sequence_no": 1
        },
        {
          "message_id": "MSG_000001_01_002",
          "session_id": "SES_000001_01",
          "sender": "agent",
          "type": "voice",
          "text": "Dạ, em sẽ tư vấn theo thông tin hiện có trong catalog.",
          "sequence_no": 2
        }
      ]
    }
  ],
  "source_policy_ids": [
    "POL-HOME-2026-001",
    "POL-COMMUNICATION",
    "POL-PROMOTION"
  ],
  "source_promotion_ids": [
    "PROMO_DELITES_NCG1805"
  ]
}
```

## 3. `sessions.jsonl`

### 3.1. Mục đích

Mỗi dòng lưu metadata của một phiên hội thoại. File này không chứa lời thoại và không chứa danh sách sản phẩm.

### 3.2. Cấu trúc

| Trường | Kiểu | Bắt buộc | Khóa | Miền/ý nghĩa | Giá trị hiện có |
|---|---|---:|---|---|---|
| `session_id` | string | Có | PK | Mẫu `SES_NNNNNN_NN`; duy nhất | 12 ID |
| `user_id` | string | Có | FK logic | Trỏ đến `conversation_scripts.user.user_id` | 6 user |
| `channel` | string enum | Có |  | `voice`, `messaging` | Cả hai |
| `platform` | string enum | Có |  | `phone`, `zalo`, `facebook_messenger`, `website_chat` | Chưa có `website_chat` |
| `timestamp` | string datetime | Có |  | ISO 8601 có timezone | 12 timestamp |
| `summary` | string | Có |  | Tóm tắt phiên, chuỗi tự do | Chuỗi tiếng Việt |
| `outcome` | string enum | Có |  | Sáu giá trị ở mục 2.6 | `ongoing`, `callback_scheduled`, `escalated` |

Generator hiện tạo timestamp theo công thức:

```text
timestamp = REFERENCE_TIME
          + 7 phút × (journey_no - 1)
          + 2 ngày × (session_index - 1)
```

### 3.3. Ví dụ trực quan

```json
{
  "session_id": "SES_000001_01",
  "user_id": "USR_000001",
  "channel": "voice",
  "platform": "phone",
  "timestamp": "2026-09-20T09:00:00+07:00",
  "summary": "Khách hỏi thông tin và giá nồi cơm điện.",
  "outcome": "callback_scheduled"
}
```

Để đọc nội dung phiên này, tìm các dòng trong `messages.jsonl` có `session_id=SES_000001_01`. Để tìm sản phẩm, làm tương tự trong `session_products.jsonl`.

## 4. `messages.jsonl`

### 4.1. Mục đích

Mỗi dòng là một lượt thoại hoặc một tin nhắn. Một session có nhiều record message cùng `session_id`.

### 4.2. Cấu trúc

| Trường | Kiểu | Bắt buộc | Khóa | Miền/ý nghĩa | Giá trị hiện có |
|---|---|---:|---|---|---|
| `message_id` | string | Có | PK | Mẫu `MSG_NNNNNN_NN_NNN`; duy nhất | 104 ID |
| `session_id` | string | Có | FK | Phải tồn tại trong `sessions.session_id` | 12 session |
| `sender` | string enum | Có |  | `customer`, `agent` | Cả hai |
| `type` | string enum | Có |  | `voice`, `text` | Cả hai |
| `text` | string | Có |  | Chuỗi có ít nhất một ký tự | Tiếng Việt |
| `sequence_no` | integer | Có | Thứ tự | Dãy liên tục từ 1 trong từng session | 1–10 trong snapshot |

Ràng buộc:

- Message đầu tiên của session có `sender=customer`.
- Sender luân phiên `customer`, `agent`, `customer`, `agent`, ...
- Nếu session là `voice`, mọi message có `type=voice`.
- Nếu session là `messaging`, mọi message có `type=text`.
- `sequence_no` không được trùng hoặc đứt đoạn trong cùng session.

### 4.3. Ví dụ trực quan

Hai dòng thuộc cùng một session:

```jsonl
{"message_id":"MSG_000001_01_001","session_id":"SES_000001_01","sender":"customer","type":"voice","text":"Tôi muốn hỏi về nồi cơm Delites NCG1805.","sequence_no":1}
{"message_id":"MSG_000001_01_002","session_id":"SES_000001_01","sender":"agent","type":"voice","text":"Dạ, em sẽ tư vấn theo thông tin hiện có trong catalog.","sequence_no":2}
```

Đọc theo `sequence_no` sẽ tái tạo được thứ tự lượt thoại.

## 5. `session_products.jsonl`

### 5.1. Mục đích

Đây là bảng nối nhiều-nhiều giữa session và sản phẩm được thảo luận. Một session có thể đề cập nhiều sản phẩm và một sản phẩm có thể xuất hiện trong nhiều session.

### 5.2. Cấu trúc

| Trường | Kiểu | Bắt buộc | Khóa | Miền/ý nghĩa | Giá trị hiện có |
|---|---|---:|---|---|---|
| `session_id` | string | Có | FK | Phải tồn tại trong `sessions.session_id` | 12 session |
| `product_id` | string | Có | FK | Chính là một giá trị `catalogs.sku` | 6 SKU duy nhất |

Khóa logic của file là cặp:

```text
(session_id, product_id)
```

Hàm chuẩn hóa loại trùng SKU trong từng session trước khi ghi file. Snapshot hiện có đúng một sản phẩm/session, nhưng schema cho phép nhiều sản phẩm/session.

### 5.3. Ví dụ trực quan

```json
{
  "session_id": "SES_000001_01",
  "product_id": "delites-ncg1805"
}
```

Ghép `product_id` với `catalogs.sku` để lấy tên, giá, thông số, tồn kho và `promotion_ids` của sản phẩm.

## 6. Liên kết và cách tái dựng một journey

Nếu không đọc bản lồng `conversation_scripts.jsonl`, có thể tái dựng dữ liệu như sau:

1. Chọn một script và lấy `script.user.user_id`.
2. Lấy các session có cùng `sessions.user_id`.
3. Với từng session, lấy messages có cùng `messages.session_id`.
4. Sắp messages tăng dần theo `sequence_no`.
5. Lấy các dòng `session_products` có cùng `session_id`.
6. Ghép `session_products.product_id` với `catalogs.sku`.

Pseudo-code:

```python
user_id = script["user"]["user_id"]
script_sessions = [s for s in sessions if s["user_id"] == user_id]

for session in script_sessions:
    session_id = session["session_id"]
    session["messages"] = sorted(
        [m for m in messages if m["session_id"] == session_id],
        key=lambda m: m["sequence_no"],
    )
    session["product_ids"] = [
        link["product_id"]
        for link in session_products
        if link["session_id"] == session_id
    ]
```

## 7. Dữ liệu bị lặp giữa các file

`conversation_scripts.jsonl` chứa bản sao của dữ liệu ở ba file chuẩn hóa:

| Dữ liệu lồng | Bản chuẩn hóa tương ứng |
|---|---|
| `conversation_scripts.sessions[]` | `sessions.jsonl` |
| `conversation_scripts.sessions[].messages[]` | `messages.jsonl` |
| `conversation_scripts.sessions[].product_ids[]` | `session_products.jsonl` |

Việc lặp này giúp đọc và đánh giá thuận tiện nhưng tạo nguy cơ lệch dữ liệu nếu chỉnh thủ công. Khuyến nghị:

- Xem `sessions.jsonl`, `messages.jsonl`, `session_products.jsonl` là các bảng chuẩn hóa dùng cho database và phân tích.
- Xem `conversation_scripts.jsonl` là bản tổng hợp được dựng từ các bảng trên.
- Không chỉnh một bản mà không tái tạo hoặc đồng bộ bản còn lại.

## 8. Các kiểm tra QA cần có

### 8.1. Khóa và khóa ngoại

- `script_id`, `session_id`, `message_id` phải duy nhất.
- Mọi `sessions.user_id` phải tồn tại trong một `conversation_scripts.user.user_id`.
- Mọi `messages.session_id` phải tồn tại trong `sessions.session_id`.
- Mọi `session_products.session_id` phải tồn tại trong `sessions.session_id`.
- Mọi `session_products.product_id` phải tồn tại trong `catalogs.sku`.
- Cặp `(session_id, product_id)` không được trùng.

### 8.2. Hội thoại

- Mỗi session có số message nằm trong giới hạn cấu hình.
- `sequence_no` liên tục từ 1.
- Sender bắt đầu bằng `customer` và luân phiên với `agent`.
- `message.type` khớp `session.channel`.
- Tóm tắt và outcome phải phù hợp với nội dung hội thoại.

### 8.3. Đa phiên và đa kênh

- `is_multi_session=true` khi và chỉ khi script có ít nhất 2 session.
- `is_multi_channel=true` khi và chỉ khi tập channel chứa cả `voice` và `messaging`.
- Mọi script đa kênh phải đồng thời là script đa phiên.
- Ví dụ 2 session `phone` và 1 session `zalo` có tổng cộng 3 session; cả hai cờ đều bằng `true`.

### 8.4. Đồng nhất bản lồng và bản chuẩn hóa

Với mỗi session trong `conversation_scripts`:

- Metadata phải giống record cùng `session_id` trong `sessions.jsonl`.
- Mảng `messages` phải giống các record trong `messages.jsonl` sau khi sắp theo `sequence_no`.
- Mảng `product_ids` phải bằng tập `product_id` trong `session_products.jsonl`.

## 9. Điểm cần lưu ý nếu chỉ giữ bốn output này

### 9.1. Không có `users.jsonl` riêng

Thông tin user vẫn được giữ đầy đủ trong `conversation_scripts.user`. `sessions.user_id` tham chiếu logic đến object này.

### 9.2. `sessions.jsonl` chưa có `script_id`

Schema hiện tại suy ra script của session qua `user_id`, dựa trên giả định một user tương ứng một script. Nếu sau này một user có nhiều script, nên thêm:

```json
{
  "session_id": "SES_000001_01",
  "script_id": "SCRIPT_000001",
  "user_id": "USR_000001"
}
```

hoặc tạo bảng nối `script_sessions.jsonl`.

### 9.3. Nguồn sự thật nên được quy định rõ

Pipeline nên ghi trong manifest rằng:

```text
sessions.jsonl + messages.jsonl + session_products.jsonl = dữ liệu chuẩn hóa
conversation_scripts.jsonl = bản lồng được dẫn xuất
```

Quy ước này ngăn việc hai bản cùng được sửa độc lập và trở nên không nhất quán.
