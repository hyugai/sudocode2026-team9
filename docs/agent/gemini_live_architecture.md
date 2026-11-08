# Kiến trúc pipeline realtime voice với Gemini Live

Đối chiếu mã nguồn ngày **26/10/2026**. Tài liệu mô tả phần đang được triển khai trong repository, bao gồm bản sửa bộ đệm audio và khôi phục AudioContext. Các giá trị mặc định có thể được thay đổi qua environment ở những nơi code cho phép.

Nhánh realtime dùng model `gemini-3.8-live` để nhận và sinh audio trực tiếp. Backend quản lý phiên, identity, quyền gọi tool và ghi customer memory. Nhánh chat text/upload ghi âm tiếp tục đi qua DeepAgent.

## 1. Ranh giới giữa các nhánh

| Thành phần | Chat text / upload ghi âm | Realtime voice |
|---|---|---|
| Input | Tin nhắn hoặc một file ghi âm cho mỗi lượt | Audio microphone liên tục |
| Nhận dạng giọng nói | Zipformer local khi upload file | Gemini Live xử lý audio; backend nhận transcript kèm theo |
| Điều phối hội thoại | DeepAgent model/tool loop | VoiceSessionController và Gemini Live session |
| Chuẩn bị nghiệp vụ | Trước khi gọi DeepAgent | Khi cần context cho function call và khi finalize lượt |
| Phản hồi | JSON hoàn chỉnh | Audio và JSON events qua WebSocket |
| Tool nghiệp vụ | Read prefetch, mutation đã xác nhận và tool loop hiện tại | Function calling với tool chỉ đọc, kiểm tra lại ở backend |
| Memory | Persister hiện có qua persist_shared | Cùng persister, thêm voice journal và prepared write batch |
| State hội thoại | ConversationState của chat | ConversationState riêng của phiên voice |

Hai nhánh dùng chung **customer_id và canonical customer memory**, không dùng chung một object state đang thay đổi. Mỗi phiên voice được cấp conversation_id mới dạng `live-{session_id}`. Chuyển chế độ trên UI không chuyển nguyên lịch sử chat hay checkpoint DeepAgent vào Gemini; phiên voice hydrate lại dữ liệu khách và memory đã commit.

**Voice không gọi lại DeepAgentHarness.run_turn cho mỗi audio chunk hoặc function call.** LLMPerceiver vẫn có thể được gọi trên transcript để phân tích nghiệp vụ; LLMPersister có thể gọi LLM để học memory tùy cấu hình. Đây là các tác vụ khác với model native audio của Gemini Live.

## 2. Sơ đồ kiến trúc tổng thể

~~~mermaid
flowchart TB
    UI["Web: chọn chế độ"] --> CHAT["Chat text / upload ghi âm"]
    UI --> PANEL["VoicePanel + VoiceClient"]

    CHAT --> TEXTAPI["HTTP / SSE chat API"]
    TEXTAPI --> DEEP["DeepAgentHarness"]

    PANEL <-->|"Audio binary + JSON events"| ROUTER["Voice HTTP / WebSocket router"]
    ROUTER --> MANAGER["VoiceSessionManager"]
    MANAGER --> CTRL["VoiceSessionController"]
    CTRL <-->|"Audio, transcript, function calls"| ADAPTER["GeminiLiveClient"]
    ADAPTER <-->|"Google Live API"| GEMINI["gemini-3.8-live"]

    DEEP --> PREP["CHUNG: identity, hydrate, NLU, retrieval, CallBrief"]
    CTRL --> PREP
    DEEP --> POLICY["CHUNG: tool policy và canonical protocol"]
    CTRL --> DISPATCH["Voice read-only dispatcher"]
    DISPATCH --> POLICY

    DEEP --> MCP["CHUNG: MCP tool registry"]
    DISPATCH --> MCP
    MCP --> BUSINESS["CRM / catalog / inventory / pricing / knowledge"]
    PREP --> CRM[("PostgreSQL CRM")]
    PREP --> MEMORY[("Canonical customer memory")]

    CTRL --> JOURNAL[("PostgreSQL: voice_turn_journal")]
    CTRL --> WRITER["CHUNG: customer writer + persister"]
    DEEP --> WRITER
    WRITER --> MEMORY
    DISPATCH -->|"Memory archive đọc trực tiếp repository"| MEMORY
~~~

Màu sắc không được dùng để phân biệt trách nhiệm; các node có chữ **CHUNG** là phần được chia sẻ. Canonical customer memory và bảng voice journal có mục đích khác nhau, dù cùng phục vụ việc nhớ thông tin khách.

### Vòng đời dependency

FastAPI lifespan khởi tạo harness hiện tại trước. Harness mở các MCP server qua stdio, giữ AsyncExitStack và sở hữu vòng đời kết nối. Voice router lấy các dependency đã có bằng `ConversationServices.from_harness(harness)`.

Voice sử dụng cùng registry tool, CRM adapter, repository và persister. Khi shutdown, ứng dụng dừng voice trước rồi mới đóng harness/MCP. Vì vậy, dù đường hội thoại riêng, **backend voice hiện vẫn phụ thuộc quá trình khởi tạo harness chung**.

## 3. Các module chính

Các đường dẫn dưới đây tính từ repository root.

| Module | Trách nhiệm |
|---|---|
| `src/web/app/page.tsx` | Chuyển chế độ chat/voice; giữ giao diện và lịch sử chat riêng |
| `src/web/components/voice-panel.tsx` | Trạng thái kết nối, transcript, bắt đầu/kết thúc, mute và thông báo memory |
| `src/web/utils/voice-api.ts` | HTTP bootstrap, xác thực WebSocket, ghép metadata/audio, lọc generation và cleanup phiên |
| `src/web/utils/voice-audio.ts` | Sở hữu microphone, AudioContext, các worklet; resume audio và giải phóng tài nguyên |
| `src/web/public/audio/voice-capture-worklet.js` | Resample microphone thành PCM16 16 kHz, frame 20 ms, phát hiện speech_start cục bộ |
| `src/web/public/audio/voice-playback-worklet.js` | Đệm audio 24 kHz, resample ra thiết bị, flush và báo playback progress |
| `src/telesale_agent/entrypoints/api/voice.py` | HTTP/WS endpoints, feature flag, API key, Origin và session authorization |
| `src/telesale_agent/application/realtime/session.py` | Registry phiên trong RAM, owner/ticket, giới hạn phiên và lease một worker |
| `src/telesale_agent/application/realtime/controller.py` | Điều phối audio/events, turn, tool tasks, finalize, recovery và reconnect |
| `src/telesale_agent/adapters/llm/gemini_live.py` | Cấu hình và I/O của Google Gen AI SDK; audio, function response và resume handle |
| `src/telesale_agent/application/realtime/context.py` | System instructions, CallBrief đã che PII và function declarations |
| `src/telesale_agent/application/realtime/tool_dispatch.py` | Kiểm tra schema, policy, bind identity và thực thi tool chỉ đọc |
| `src/telesale_agent/application/conversation/services.py` | Tập dependency dùng chung, không chứa graph hoặc Live socket |
| `src/telesale_agent/application/conversation/prepare.py` | Resolve/hydrate, perception, retrieval, refresh memory và dựng CallBrief |
| `src/telesale_agent/application/conversation/tool_policy.py` | Policy chọn tool theo intent, transcript và facts |
| `src/telesale_agent/application/tools/protocol.py` | Chuẩn hóa tên/args/result và tạo AgentStep từ tool evidence |
| `src/telesale_agent/adapters/mcp/runtime.py` | Kết nối MCP và tạo registry; caller sở hữu exit stack |
| `src/telesale_agent/application/memory/coordinator.py` | Khóa ghi theo customer, dùng chung persister và replay prepared batch |
| `src/telesale_agent/adapters/db/voice_store.py` | Lưu voice turn journal bằng SQLAlchemy |
| `src/telesale_agent/core/realtime.py` | SessionInit và VoiceTurnRecord, không phụ thuộc SDK |
| `src/telesale_agent/config/realtime.py` | Model, feature flag, allowlist Origin, timeout và giới hạn tài nguyên |

Các business executor trong `application/tools/reads.py` và `mutations.py` đã được tách khỏi vị trí cũ; DeepAgent giữ các façade tương thích. Tuy nhiên, voice dispatcher hiện gọi read tool từ registry trực tiếp, không chạy nguyên chuỗi prefetch/mutation của chat.

## 4. Khởi tạo một phiên voice

~~~mermaid
sequenceDiagram
    participant Web as VoiceClient
    participant API as Voice API
    participant Manager as SessionManager
    participant Shared as Shared services
    participant DB as Voice journal
    participant Live as Gemini Live

    Web->>API: GET /api/voice/capabilities
    Note over Web: Người dùng bấm bắt đầu; mở microphone/audio
    Web->>API: POST /api/voice/sessions + customer_phone
    API->>Manager: create(phone)
    opt Manager chưa initialize
        Manager->>DB: Kiểm tra bảng journal và lấy pending jobs
        Manager->>Shared: Thử recovery memory
    end
    Manager->>Shared: Resolve identity, hydrate, dựng CallBrief
    Manager-->>API: Session, owner token, connect ticket
    API-->>Web: Thông tin phiên
    Web->>API: Mở WebSocket và gửi authenticate
    API->>Manager: claim(owner, ticket), kiểm tra Origin
    API->>Live: Controller mở Gemini Live session
    API-->>Web: session_ready
    Web->>API: Bắt đầu gửi frame microphone
~~~

Chi tiết thực thi:

1. UI đọc capabilities để quyết định cho phép bắt đầu; microphone chỉ được yêu cầu khi người dùng bấm nút.
2. HTTP bootstrap kiểm tra `API_KEY` nếu backend có cấu hình; thời gian tạo phiên được giới hạn 45 giây.
3. Manager kiểm tra journal, lấy PostgreSQL advisory lock khi dùng PostgreSQL và chạy recovery ở lần initialize đầu tiên.
4. `initialize_customer()` dùng **SessionInit**, resolve phone hint, hydrate CRM/memory và dựng CallBrief. Không tạo câu thoại khách giả và không chạy NLU cho bước setup.
5. Session giữ owner/ticket dưới dạng SHA-256 hash trong RAM. Ticket có thời hạn 120 giây và dùng một lần.
6. Sau khi WebSocket được accept, client phải gửi JSON authenticate trong 10 giây. Tokens không được đưa vào query string URL.
7. GeminiLiveClient mở model ở backend. Google API key nằm phía server, khác với API_KEY dùng bảo vệ ứng dụng.

### Các định danh

| ID | Phạm vi và ý nghĩa |
|---|---|
| `session_id` | Định danh kết nối voice do manager cấp |
| `conversation_id` | `live-{session_id}`; liên kết các lượt trong phiên |
| `customer_id` | Identity do backend resolve; khóa liên kết CRM và canonical memory |
| `turn_id` | UUID của một VoiceTurnRecord |
| `generation` | Thứ tự audio để loại dữ liệu cũ; tăng khi mở turn hoặc ngắt lời |
| `revision` | Tăng khi nhận input transcription, dùng kiểm tra context cache còn hợp lệ |
| `call_id` | ID function call từ provider, dùng theo dõi task và kết quả |
| `source_id` | `voice:{conversation_id}:{turn_id}`; nguồn ổn định cho journal và memory |

## 5. Pipeline khi đang hội thoại

~~~mermaid
flowchart TB
    MIC["Microphone"] --> CAPTURE["Capture worklet: PCM16 / 16 kHz / 20 ms"]
    CAPTURE --> CLIENT["VoiceClient"]
    CLIENT -->|"WebSocket binary"| INPUT["Controller.client_loop"]
    INPUT --> LIVE["GeminiLiveClient / Gemini Live"]

    LIVE --> EVENTS["Controller.model_loop / provider_event"]
    EVENTS --> AUDIO["Audio output"]
    AUDIO --> OUTBOX["Outbox / sender: metadata rồi binary"]
    OUTBOX --> PLAY["Playback worklet / loa"]

    EVENTS --> TRANSCRIPT["Input / output transcription"]
    TRANSCRIPT --> RECORD["VoiceTurnRecord + revision"]
    TRANSCRIPT --> TEXTUI["JSON transcript events tới UI"]

    EVENTS --> TOOL["Function calls chạy background task"]
    RECORD --> PREP["Chuẩn hóa transcript, NLU, retrieval, CallBrief"]
    PREP --> TOOL
    TOOL -->|"FunctionResponse"| LIVE

    EVENTS --> FINAL["Turn complete / interrupted / đóng phiên"]
    RECORD --> FINAL
    FINAL --> PERSIST["Finalize và memory job"]
    PERSIST --> JOURNAL[("Voice journal")]
    PERSIST --> MEMORY[("Canonical memory")]
~~~

Audio output, transcript và function calls có thể cùng xuất hiện trong một provider event. Controller xử lý tất cả các phần, không dùng nhánh if/elif khiến audio làm mất transcript hoặc tool event.

### Chuẩn bị context từ transcript

`turn_context()` tạo bản sao ConversationState, xóa memory_deltas của bản sao, chuẩn hóa transcript rồi gọi `prepare_context()`. Các bước được tái sử dụng là identity/hydrate, perception, retrieval theo intent, refresh canonical memory và CallBrief.

Context được cache theo revision, có khóa riêng từng turn. Nếu transcript đổi trong lúc prepare, context đó không được chấp nhận làm cache cho revision mới.

**Đường audio không chờ toàn bộ NLU/retrieval/persist của mỗi lượt.** Context được chuẩn bị khi tool cần hoặc khi finalize; kết quả retrieval trên TurnContext không tự được bơm vào Live socket. Model nhận CallBrief lúc setup và dữ liệu context/tool qua function responses.

### Ba loại hoàn tất khác nhau

- **Model complete:** provider báo kết thúc tương tác; chưa chứng minh mọi audio đã phát.
- **Playback progress:** client báo số mẫu đã tiêu thụ tại worklet; đây là ước lượng tiến độ phía client, không xác nhận người dùng thực sự nghe được.
- **Memory committed:** backend đã xử lý memory job; có thể không thêm fact nếu thiếu identity hoặc persister không tạo thay đổi.

Các mốc này được giữ riêng, không gộp thành một sự kiện complete của chat/SSE.

## 6. Tool calling và quyền thực thi

~~~mermaid
sequenceDiagram
    participant Live as Gemini Live
    participant Ctrl as Controller
    participant Prep as Shared context
    participant Dispatch as Read dispatcher
    participant Tool as MCP / memory repository

    Live->>Ctrl: function_calls: id, name, args
    Ctrl->>Ctrl: Tạo background task, kiểm tra call_id
    Ctrl->>Prep: Lấy context theo transcript/revision
    Ctrl->>Dispatch: name, args, identity/context server
    Dispatch->>Dispatch: Kiểm tra mode, schema, policy
    Dispatch->>Tool: Read đã bind identity và ngày
    Tool-->>Dispatch: Result hoặc lỗi
    Dispatch-->>Ctrl: Public result + canonical evidence
    Ctrl->>Live: FunctionResponse cùng call_id
    Ctrl->>Ctrl: Lưu evidence cho memory; phát operation_update
~~~

Trước khi chuẩn bị context, task có thể chờ transcript tối đa khoảng 1 giây; transcript đã ổn định 0,4 giây có thể được dùng cho **read** dù chưa có finished flag. Nếu thiếu context phù hợp, dispatcher trả yêu cầu làm rõ thay vì cho thực thi tool nghiệp vụ.

### Tập tool hiện được công bố

| Tool | Cách thực thi / ràng buộc |
|---|---|
| `get_customer_context` | Refresh memory, dựng lại CallBrief; tool nội bộ của voice |
| `search_catalog` | MCP; chỉ công bố nếu registry có tool |
| `check_inventory` | MCP; backend thêm ngày theo múi giờ Việt Nam |
| `get_pricing_quote` | MCP; backend bind customer_id, customer_phone và ngày |
| `search_policy` / `search_knowledge_base` | MCP; giới hạn query/k theo schema |
| `search_customer_memory_archive` | Khi có trong registry, dispatcher đọc repository trực tiếp với customer_id từ backend |

Backend kiểm tra tên tool, field thừa, field bắt buộc, kiểu và giới hạn giá trị. Policy chung tiếp tục giới hạn tool theo intent/transcript/facts; archive có kiểm tra identity riêng. Model không được tự truyền customer_id hoặc ngày để đổi phạm vi truy vấn.

Thực thi MCP/read repository có timeout mặc định 25 giây; thời gian chờ transcript và chuẩn bị context/NLU nằm ngoài timeout này. Kết quả được chuẩn hóa thành hai phần:

- **Evidence cho memory:** canonical name, arguments do server bind và result thực tế, kể cả kết quả lỗi.
- **Result cho Gemini:** dữ liệu đã che PII ở string leaves, giữ cấu trúc và kiểu số; giới hạn khoảng 16.000 ký tự JSON.

Một call_id đang chạy không được tạo task thứ hai. Kết quả đã có được cache trong phiên để trả lại khi provider lặp cùng call_id. Đây là chống lặp read trong phiên, không phải operation ledger bền vững cho mutation.

**Tool ghi bị khóa:** tạo/sửa đơn, callback và handoff không có trong declarations; settings chỉ chấp nhận `off` hoặc `read_only`. Registry chung vẫn có thể chứa tool ghi cho chat, nhưng điều đó không cấp quyền cho voice.

## 7. Xử lý customer memory

### 7.1. Ba lớp dữ liệu

| Lớp | Dữ liệu | Nơi lưu |
|---|---|---|
| State phiên | Identity, CallBrief, snapshot memory, recent messages và turn records | RAM backend |
| Voice journal | Transcript, output text, interruption, tool evidence, played_samples, prepared operations và status | PostgreSQL, bảng `voice_turn_journal` |
| Canonical memory | Facts, atomic facts, episodes, foresights và các phần memory hiện có | Repository file .md hoặc object storage theo cấu hình chung |

Bảng voice_turn_journal dùng source_id làm primary key; các cột còn lại là customer_id, payload (JSON), prepared (JSON), status và updated_at. Journal lưu công việc cần hoàn tất, không phải bảng lưu toàn bộ Live session để nối lại WebSocket sau restart.

Raw audio không được lưu vào journal. Transcript và tool evidence vẫn có thể chứa thông tin khách; việc che dữ liệu gửi model không đồng nghĩa journal đã được che toàn bộ PII.

### 7.2. Chốt một lượt

Controller schedule một finalizer cho mỗi turn khi có model completion, interruption hoặc đóng phiên. Finalizer:

1. Chờ 0,5 giây, tiếp tục đợi đến khi input transcript yên ít nhất 0,4 giây, rồi chờ các read task liên quan.
2. Với model_complete, không bị interrupted và có input text, backend có thể chốt input_finished dù provider không gửi finished riêng.
3. Disconnect hoặc interruption tự nó không nâng transcript chưa hoàn chỉnh thành hoàn chỉnh.
4. Ghi journal: `pending` nếu input_finished; `incomplete` nếu chưa chốt input.
5. Với input đã chốt, chuẩn bị TurnContext, chiếu tool evidence thành AgentStep và gọi commit_voice.
6. Sau commit, cập nhật snapshot, số turn, recent messages và CallBrief trong state; phát `memory_committed`. Khi có lỗi, ghi log và có thể phát `memory_pending`.

Interim transcription chỉ phục vụ UI, không trực tiếp đưa vào canonical memory. Nếu người dùng đã nói xong nhưng ngắt lời agent đang phát, input đã chốt vẫn có thể được persist; output của agent được đánh dấu bị ngắt.

### 7.3. Prepared batch và đường ghi dùng chung

~~~mermaid
flowchart TB
    TURN["Turn đã chốt input"] --> PENDING["Journal: pending"]
    PENDING --> LOCK["Khóa theo customer trong process"]
    LOCK --> REFRESH["Reload canonical memory"]
    REFRESH --> CHECK{"Đã có prepared batch?"}
    CHECK -->|"Chưa"| DRAFT["Chạy persister trên RecordingRepository trong RAM"]
    DRAFT --> PREPARED["Lưu operations + writes: prepared"]
    CHECK -->|"Có"| APPLY
    PREPARED --> APPLY["Apply batch bằng TurnMemoryWriteSession"]
    APPLY --> CANONICAL[("Canonical memory")]
    CANONICAL --> DONE["Journal: committed"]

    PARTIAL["Input chưa hoàn chỉnh"] --> INCOMPLETE["Journal: incomplete"]
~~~

Voice dùng **persister đã được bootstrap chọn**: TurnMemoryPersister hoặc LLMPersister. RecordingRepository ghi lại hiệu ứng của persister thay vì ghi trực tiếp vào canonical memory ở bước chuẩn bị.

Khi đã lưu prepared batch, retry sử dụng lại operations, không chạy lại LLM learning cho batch đó. Append có marker theo source để bỏ qua phần đã ghi; upsert_fact kiểm tra giá trị trước đó/giá trị đích để tránh prepared batch cũ ghi đè một fact đã thay đổi.

Chat gọi `persist_shared()`, voice gọi `commit_voice()`; cả hai dùng `customer_writer(customer_id)` và refresh memory trong khóa trước khi ghi. Khóa chỉ có hiệu lực trong cùng process/event loop. Không có distributed CAS hoặc transaction nguyên tử xuyên PostgreSQL và file/object storage.

### 7.4. Recovery và giới hạn

`recover_memory()` chạy khi voice manager initialize lần đầu, thường ở POST tạo phiên đầu tiên sau khi backend restart. Nó thử tối đa 30 job pending/prepared, hydrate khách rồi hoàn thành hoặc replay batch. Job không đủ input được đánh dấu incomplete.

Hiện chưa có worker retry định kỳ. Job còn lại/chưa thành công cần lần initialize tiếp theo hoặc cơ chế vận hành bổ sung.

Recovery dựa trên journal **đã ghi thành công**. Nếu PostgreSQL lỗi ngay khi lưu turn, memory_pending không bảo đảm đã tồn tại một durable job. Tương tự, audio/turn chỉ nằm trong RAM trước finalize có thể mất khi process bị kill.

`committed` là trạng thái job đã xử lý; trường hợp không có customer_id hoặc persister, commit_voice có thể kết thúc job mà không ghi canonical fact.

## 8. Ngắt lời và chống phát audio cũ

Có hai tín hiệu khác nhau:

1. **Speech_start cục bộ:** capture worklet phát hiện năng lượng giọng nói; client flush playback ngay và gửi input_started. Microphone tiếp tục truyền audio để Gemini tự xử lý VAD. Tín hiệu này không tự gọi business mutation hoặc gửi manual ActivityStart tới Google.
2. **Interrupted từ Gemini:** controller tăng generation, đánh dấu turn cũ bị ngắt, schedule finalize, hủy read task của turn cũ và gửi event interrupted về client.

Khi nhận interrupted, VoiceClient bỏ metadata audio đang chờ, nâng generation tối thiểu và flush worklet với generation đó. Sender, client và worklet cùng lọc audio cũ; gói đến muộn không được làm đầy lại bộ đệm đã flush.

Speech_start cục bộ chỉ dọn audio đang đợi; việc nâng generation theo interruption được đồng bộ bằng event backend. Đây là hai bước khác nhau, không nên coi phát hiện cục bộ là xác nhận provider đã hủy lượt.

Cancel read tool không phải rollback nghiệp vụ. Nhánh hiện tại khóa mutation nên chưa có bài toán hủy/đối soát write đang commit qua voice. Khi bổ sung tool ghi cần operation ledger, idempotency và reconciliation riêng.

## 9. Audio transport, buffering và AudioContext

| Chặng | Định dạng / cách xử lý |
|---|---|
| Microphone → capture worklet | Mono; thiết bị có thể chạy 44,1 hoặc 48 kHz; yêu cầu echo cancellation, noise suppression và auto gain |
| Capture → backend | PCM16 mono 16 kHz, 320 samples / 640 bytes mỗi frame 20 ms |
| Backend → Gemini | Blob `audio/pcm;rate=16000` |
| Gemini → backend → client | PCM16 24 kHz; mỗi audio payload có JSON metadata đi trước |
| Playback → thiết bị | Worklet resample 24 kHz theo sampleRate thực tế của AudioContext |

VoiceAudio sở hữu một AudioContext cho capture/playback. Capture đi qua gain bằng 0 để microphone không tự phát lại ra loa. Playback được tạo như một source node **0 input, 1 output mono** và nối trực tiếp ra destination.

Playback buffer khởi tạo với dung lượng 2 giây, tăng theo lượng audio đang chờ, tối đa **60 giây**. Audio được phát ngay khi có dữ liệu; dung lượng này không phải thời gian phải chờ trước khi phát. Buffer được nới để tiếp nhận audio sinh theo đợt, vẫn giữ giới hạn bộ nhớ.

AudioContext được kiểm tra/resume trước và sau cấp quyền microphone, khi state thay đổi và khi nhận audio. Resume có timeout 3 giây. Nếu không phục hồi được hoặc processor dừng, client báo lỗi cụ thể và giải phóng phiên; không chờ tới khi buffer đầy mới suy luận là mạng chậm.

Worklet báo playback_progress mỗi khoảng 6.000 source samples, tương đương 0,25 giây audio 24 kHz. Mốc này đo lượng worklet tiêu thụ, không đo trực tiếp phần âm thanh người dùng đã nghe.

### Giới hạn và quá tải

- Backend kiểm tra binary PCM không rỗng, byte length chẵn và tối đa 6.400 bytes/frame.
- Control JSON từ client tối đa 2.048 ký tự.
- Outbox backend mặc định 128 item, gồm cả audio và events; đây không phải giới hạn tính theo giây audio.
- Khi socket gửi microphone bị dồn hơn 32.000 bytes, VoiceClient báo lỗi và đóng phiên.
- Nếu playback vượt cap 60 giây, worklet báo overflow một lần cho generation đó; client kết thúc phiên.
- Các giới hạn này chưa tạo thành một cơ chế flow control đầu-cuối điều chỉnh tốc độ sinh của model.

## 10. Hợp đồng HTTP và WebSocket

### HTTP

| Endpoint | Vai trò / xác thực |
|---|---|
| `GET /api/voice/capabilities` | enabled, model, tools_mode, protocol_version, requires_access_code |
| `POST /api/voice/sessions` | Nhận customer_phone, trả ID và tokens; kiểm tra X-API-Key nếu có cấu hình |
| `GET /api/voice/sessions/{id}` | Đọc trạng thái bằng Bearer owner token |
| `DELETE /api/voice/sessions/{id}` | Yêu cầu đóng phiên bằng Bearer owner token |
| `WS /api/voice/sessions/{id}/stream` | Audio/control hai chiều; Origin allowlist và JSON authenticate đầu tiên |

Capabilities enabled phản ánh feature flag, không phải kết quả thử kết nối Gemini hoặc quyền truy cập model.

### Client → server

JSON đầu tiên sau khi mở socket:

~~~json
{
  "type": "authenticate",
  "owner_token": "<token do backend cấp>",
  "connect_ticket": "<ticket dùng một lần>"
}
~~~

Các message tiếp theo gồm binary PCM và JSON `input_started`, `input_audio_end`, `playback_progress`, `close`. Controller cũng hiểu control `interrupt`, nhưng speech_start của client hiện gửi input_started; hai tín hiệu không đồng nghĩa.

Mute trên UI ngừng gửi frame và gửi input_audio_end; unmute tiếp tục gửi audio. Kết thúc phiên đóng socket, dừng microphone/AudioContext và gửi DELETE để giải phóng phiên phía server.

### Server → client

| Event | Ý nghĩa |
|---|---|
| `session_ready` | Đã mở Live session, kèm model và sample rates |
| `audio` + binary frame ngay sau | Metadata gồm generation, turn_id, sample_rate rồi payload PCM |
| `transcript_interim` | Input tạm thời cho UI |
| `transcript_update` | Text tích lũy theo turn_id/role; input có thể kèm finished |
| `interrupted` | Flush audio cũ và cập nhật generation |
| `operation_update` | Trạng thái read tool completed/failed |
| `memory_committed` / `memory_pending` | Trạng thái xử lý memory của turn |
| `connection` | connected hoặc reconnecting phía provider |
| `usage` | Usage metadata từ provider |
| `error` | Lỗi kết thúc hoặc làm gián đoạn phiên |

Một sender duy nhất gửi metadata và binary theo thứ tự. VoiceClient ghép cặp hai message, dùng generation để lọc rồi chuyển PCM vào worklet. UI giữ tối đa 100 dòng transcript; state backend giữ tối đa 20 recent messages sau finalize.

## 11. Concurrency, reconnect và shutdown

Controller chạy đồng thời bốn task: nhận provider events, nhận client input, gửi outbox và đợi stop. Tool calls/finalizers là background tasks riêng để việc đọc MCP hoặc ghi memory không trực tiếp chặn vòng nhận audio.

Tuy vậy, đây vẫn là backend asyncio dùng chung tài nguyên với chat; thiết kế hiện tại chưa phải một media server chuyên dụng hoặc bằng chứng đã đạt SLA latency.

### Hai loại mất kết nối

| Trường hợp | Hành vi hiện tại |
|---|---|
| Gemini gửi GoAway hoặc provider stream lỗi | Controller flush/đánh dấu interruption, báo reconnecting và thử reconnect tối đa hai lượt trong vòng đời controller |
| Có resume handle còn dùng được | Adapter thử mở lại session bằng handle giữ trong RAM backend |
| Resume bị từ chối | Adapter bỏ handle, thử session mới với instructions/CallBrief hiện có |
| Browser mất WebSocket | VoiceClient đóng tài nguyên; người dùng chủ động mở phiên mới |
| Backend restart / hot reload | Session registry và handle trong RAM mất; journal đã lưu có thể được recovery khi manager mới initialize |

Fallback session mới không tự replay toàn bộ audio hoặc hội thoại cũ. CallBrief/canonical memory đã commit là phần context ứng dụng có thể phục hồi; context trong provider resumption là một cơ chế riêng.

Khi run kết thúc, controller hủy các vòng I/O và read task đang chờ, schedule finalize cho turn đang có, đợi memory jobs rồi đóng model. Manager shutdown đợi các runner tối đa 45 giây trước khi thả lease; sau đó FastAPI mới đóng harness/MCP.

## 12. Cấu hình và ràng buộc triển khai

| Cấu hình | Mặc định / ràng buộc |
|---|---|
| `REALTIME_VOICE_ENABLED` | false; mode vẫn hiển thị nhưng không cho bắt đầu khi disabled |
| `GEMINI_LIVE_MODEL` | gemini-3.8-live; settings từ chối model khác |
| `GEMINI_LIVE_API_VERSION` | v1beta |
| `GEMINI_LIVE_VOICE` | Kore |
| `REALTIME_TOOLS_MODE` | read_only; chỉ nhận off hoặc read_only |
| `REALTIME_MAX_SESSIONS` | 4 |
| `REALTIME_AUDIO_QUEUE_LIMIT` | 128 item |
| `REALTIME_TOOL_TIMEOUT_SECONDS` | 25 |
| `REALTIME_SESSION_IDLE_TIMEOUT_SECONDS` | 120; timeout chờ message WebSocket, không phải thời gian khách im lặng nếu vẫn gửi frame |
| `REALTIME_SESSION_MAX_SECONDS` | 600 |
| `REALTIME_ALLOWED_ORIGINS` | localhost:3000 và 127.0.0.1:3000, phải liệt kê origin cụ thể |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Credential server cho Gemini; ưu tiên GOOGLE_API_KEY |
| `API_KEY` | Tùy chọn bảo vệ bootstrap bằng mã truy cập backend |
| `CUSTOMER_MEMORY_BACKEND` | Repository file hoặc object_storage/s3 dùng chung với chat |
| `MEMORY_PERSISTER_MODE` | Chọn persister hiện có; mặc định llm_learning |

Gemini adapter cấu hình AUDIO, input/output transcription, voice, context window compression và session resumption. Nó không truyền thinking_config/thinking_level của model text sang Live setup. Việc chọn model cho NLU/DeepAgent/memory learning vẫn thuộc cấu hình LLM chung.

**Triển khai một backend worker.** PostgreSQL advisory lock ngăn voice manager thứ hai cùng lấy lease trong trường hợp thông thường. Session registry, context locks và customer writer vẫn ở RAM trong process; lease này không thay thế distributed session routing hoặc distributed memory writer.

### Giới hạn sản phẩm hiện tại

- Voice chỉ tư vấn/tra cứu. Chưa triển khai write operation ledger, mutation reconciliation hoặc chuyển nguyên phiên sang agent khác.
- Native audio được phát trực tiếp. Che PII ở context/tool result và system instructions không bảo đảm duyệt từng lời trước khi người dùng nghe; đường prepare_response/guard text của chat không được chạy trước mỗi audio chunk.
- ConversationServices có guardrail dependency, nhưng điều đó không đồng nghĩa toàn bộ guardrail của chat đã áp dụng vào audio.
- Chưa có LiveKit/WebRTC, SIP/PSTN, browser reconnect tự động hoặc triển khai nhiều worker.
- Không có background recovery worker hay retention job cho voice journal trong phạm vi module hiện tại.
- Test tự động dùng provider/tool giả lập và kho memory riêng; không thay thế kiểm thử microphone, tiếng Việt và latency trên tài khoản Gemini thật.

## 13. Kiểm chứng và tài liệu liên quan

[Test backend realtime](../../tests/test_realtime.py) bao phủ khởi tạo registry MCP dùng chung, xác thực HTTP/WS, token/ticket, event có cả audio/transcript, transcript đến muộn, interruption, tool policy, identity binding, SDK config và replay memory batch.

[Test audio frontend](../../src/web/tests/voice.test.mjs) bao phủ frame capture 20 ms, response 12 giây đến theo đợt, resampling 44,1/48 kHz, tăng buffer khi đang phát, audio cũ sau interruption, cap bộ đệm, AudioContext bị pause và cleanup khi cấp quyền microphone đến muộn.

Các tài liệu đi kèm:

- [Kế hoạch triển khai và các pha còn lại](./gemini_live_implementation_plan.md).
- [Cấu hình, migration, chạy chương trình và rollback](../deployment/gemini_live.md).
- [Kiến trúc DeepAgent của nhánh text/upload](./deep_agent_architecture.md).
- [Luồng context và memory hiện tại](./deepagent_context_memory_flow.md).
- [Voice upload và Zipformer local](../deployment/local_voice_input.md).
