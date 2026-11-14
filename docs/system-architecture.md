# Kiến trúc tổng quan hệ thống Telesales AI

## C4 — Level 1: System Context

Sơ đồ thể hiện người dùng tương tác với hệ thống và các dịch vụ bên ngoài hỗ trợ tư vấn bán hàng bằng tiếng Việt.

```mermaid
flowchart LR
    customer["Khách hàng<br/>[Person]<br/>Cần tư vấn sản phẩm và hỗ trợ mua hàng"]
    salesman["Nhân viên bán hàng — Salesman<br/>[Person]<br/>Xem lại các cuộc hội thoại đã lưu"]

    system["Hệ thống Telesales AI<br/>[Software System]<br/>Tư vấn qua text và giọng nói,<br/>ghi nhớ nhu cầu và lưu hội thoại"]

    gemini["Google Gemini API<br/>[External Software System]<br/>Cung cấp mô hình ngôn ngữ<br/>và hội thoại giọng nói realtime"]

    customer <-->|"Gửi text hoặc audio qua web;<br/>nhận trả lời bằng văn bản hoặc giọng nói"| system
    salesman <-->|"Đăng nhập, tìm và xem hội thoại;<br/>đọc bản chép lời, tóm tắt và thông tin khách đã lưu"| system

    system <-->|"Gửi ngữ cảnh hoặc audio; nhận phản hồi"| gemini

    classDef person fill:#08427b,color:#fff,stroke:#052e56;
    classDef mainSystem fill:#1168bd,color:#fff,stroke:#0b4884;
    classDef external fill:#666,color:#fff,stroke:#444;
    class customer,salesman person;
    class system mainSystem;
    class gemini external;
```

### Chức năng từng thành phần

| Thành phần | Chức năng |
| --- | --- |
| Khách hàng | Nhập thông tin nhận diện, hỏi đáp bằng text, gửi file ghi âm hoặc trò chuyện giọng nói realtime. |
| Nhân viên bán hàng — Salesman | Xem hội thoại Chat/Voice đã lưu, bản chép lời, tóm tắt và thông tin khách; chỉ có quyền xem. |
| Hệ thống Telesales AI | Nhận diện khách, tra cứu sản phẩm/giá/tồn kho/chính sách, tư vấn và ghi nhớ ngữ cảnh qua các lần tương tác. |
| Google Gemini API | Phân tích và sinh câu trả lời khi được cấu hình; Gemini Live nhận và trả audio cho hội thoại realtime. |

Database trên Neon, index trên Pinecone và kho customer memory do dự án quản lý thuộc phạm vi hệ thống. Chúng được mở rộng ở tầng Container bên dưới.

## C4 — Level 2: Container Diagram

Tầng này thể hiện các ứng dụng/process và kho dữ liệu của hệ thống: mỗi khối có công nghệ, trách nhiệm chính và giao thức kết nối. Cấu trúc được đối chiếu với code trong repository; cấu hình lưu trữ thực tế phụ thuộc môi trường deploy.

### Sơ đồ

```mermaid
flowchart TB
    customer2["Khách hàng<br/>[Person]"]
    salesman2["Nhân viên bán hàng — Salesman<br/>[Person]"]
    google["Google Gemini API<br/>[External Software System]<br/>Cung cấp LLM và hội thoại giọng nói"]

    subgraph telesales["Hệ thống Telesales AI — Software System Boundary"]
        browser["Web UI<br/>[Container: React / TypeScript]<br/>Giao diện khách hàng và Salesman"]
        web["Web Application<br/>[Container: Next.js / Node.js]<br/>Phục vụ giao diện và proxy HTTP"]
        api["Backend<br/>[Container: Python / FastAPI]<br/>Cung cấp API và điều phối tư vấn AI"]

        mcp_tools["MCP Tool Servers<br/>[Container group: Python / FastMCP]<br/>Cung cấp công cụ nghiệp vụ và kiến thức"]

        postgres[("Application Database<br/>[Container: PostgreSQL trên Neon]<br/>Lưu dữ liệu nghiệp vụ và hội thoại")]
        vector[("Knowledge Store<br/>[Container: Pinecone index]<br/>Lưu kiến thức và chính sách cửa hàng")]
        memory[("Customer Memory Store<br/>[Container: Markdown trên filesystem hoặc S3]<br/>Lưu thông tin học được về khách hàng")]
    end

    customer2 -->|"Sử dụng"| browser
    salesman2 -->|"Sử dụng"| browser
    browser <-->|"HTTPS"| web
    web <-->|"HTTP(S): chuyển tiếp API"| api
    browser <-->|"WSS: voice; HTTPS: guest API"| api

    api <-->|"MCP / stdio"| mcp_tools
    api -->|"Đọc/ghi — SQL"| postgres
    mcp_tools -->|"Đọc/ghi — SQL"| postgres
    mcp_tools -->|"Tra cứu — HTTPS"| vector
    api <-->|"HTTPS / WSS"| google
    api -->|"Đọc/ghi — File I/O hoặc S3/HTTPS"| memory

    classDef actor fill:#08427b,color:#fff,stroke:#052e56;
    classDef application fill:#1168bd,color:#fff,stroke:#0b4884;
    classDef store fill:#438dd5,color:#fff,stroke:#0b4884;
    classDef externalService fill:#666,color:#fff,stroke:#444;
    class customer2,salesman2 actor;
    class browser,web,api,mcp_tools application;
    class postgres,vector,memory store;
    class google externalService;
    style telesales fill:transparent,stroke:#64748b,stroke-width:2px;
```

### Chức năng từng container

| Container | Chức năng |
| --- | --- |
| Web UI | Chạy trong trình duyệt; cung cấp chat, nhập/phát audio và màn hình xem lịch sử cho Salesman. |
| Web Application | Chạy Next.js phía server; phục vụ trang/assets và chuyển tiếp HTTP API đến backend. |
| Backend | Xác thực, phân quyền, xử lý tư vấn text/voice và lưu kết quả hội thoại. |
| MCP Tool Servers | Cung cấp công cụ CRM, catalog, tồn kho, báo giá, đơn hàng, tra cứu chính sách, callback và handoff. |
| Application Database | Lưu catalog, CRM, đơn hàng, tài khoản, lịch sử Chat và journal Voice. |
| Knowledge Store | Lưu các đoạn kiến thức/chính sách để tìm kiếm phục vụ tư vấn. |
| Customer Memory Store | Lưu nhu cầu, sở thích và thông tin đã học qua nhiều cuộc hội thoại; dùng filesystem hoặc Neon Object Storage theo cấu hình. |

## C4 — Level 3: Component Diagram

Chia Backend thành **ba góc nhìn nhỏ**. Đọc từ **trái sang phải**: bên gọi → API → bộ phận xử lý → nơi lưu dữ liệu/dịch vụ được dùng. Mũi tên thể hiện quan hệ gọi/sử dụng; không phải toàn bộ thứ tự thực thi.

**API** nhận request; **Service** xử lý; **Repository/Adapter** đọc/ghi dữ liệu hoặc kết nối dịch vụ khác. Các hình chỉ giữ kết nối chính. Kiểm tra quyền dùng chung được ghi bằng chú thích để tránh đường nối chéo.

### 3.1. Tài khoản và lịch sử hội thoại

Đăng nhập đi qua bộ phận xác thực. Xem lịch sử, gửi feedback và màn hình Salesman đi qua repository để đọc/ghi database.

```mermaid
flowchart LR
    accountUI["Web UI<br/>[Container: React]"]
    subgraph accountBackend["Backend — Container: Python / FastAPI"]
        authAPI["Auth API<br/>[Component: FastAPI]<br/>Đăng ký / đăng nhập"]
        conversationAPI["Conversation API<br/>[Component: FastAPI]<br/>Hội thoại cá nhân"]
        feedbackAPI["Feedback API<br/>[Component: FastAPI]<br/>Đánh giá câu trả lời"]
        salesmanAPI["Salesman API<br/>[Component: FastAPI]<br/>Lịch sử khách hàng"]
        authService["Account & Session Access<br/>[Component: Python / SQLAlchemy]<br/>Xác minh và lưu tài khoản/session"]
        appRepository["App Data Repository<br/>[Component: SQLAlchemy]<br/>Hội thoại và feedback"]
        historyReader["Salesman History Reader<br/>[Component: SQLAlchemy]<br/>Transcript và snapshot đã lưu"]
    end
    accountDB[("Application Database<br/>[Container: PostgreSQL / Neon]")]

    accountUI -->|"HTTPS/JSON"| authAPI
    accountUI -->|"HTTPS/JSON"| conversationAPI
    accountUI -->|"HTTPS/JSON"| feedbackAPI
    accountUI -->|"HTTPS/JSON"| salesmanAPI
    authAPI -->|"Xác minh / quản lý session"| authService
    conversationAPI -->|"Tạo / xem / kết thúc"| appRepository
    feedbackAPI -->|"Lưu / xóa góp ý"| appRepository
    salesmanAPI -->|"Tìm / đọc lịch sử"| historyReader
    authService -->|"SQL: đọc/ghi"| accountDB
    appRepository -->|"SQL: đọc/ghi"| accountDB
    historyReader -->|"SQL: chỉ đọc"| accountDB

    classDef component fill:#1168bd,color:#fff,stroke:#0b4884;
    classDef container fill:#438dd5,color:#fff,stroke:#0b4884;
    class authAPI,conversationAPI,feedbackAPI,salesmanAPI,authService,appRepository,historyReader component;
    class accountUI,accountDB container;
    style accountBackend fill:transparent,stroke:#1168bd,stroke-width:2px;
```

API lịch sử/feedback kiểm tra chủ tài khoản; Salesman API yêu cầu role `salesman`. Những kiểm tra này dùng chung dependency trong `auth.py`. Salesman chỉ đọc bản lưu, không chạy lại AI để tạo nội dung mới. HTTP của account được Next.js chuyển tiếp về backend.

### 3.2. Chat và Voice

Text và file ghi âm dùng chung pipeline Chat; file ghi âm được nhận dạng bằng ASR local. Voice realtime dùng bộ điều phối riêng, trao đổi audio với Gemini Live.

```mermaid
flowchart LR
    chatUI["Web UI<br/>[Container: React]"]
    subgraph chatBackend["Backend — Container: Python / FastAPI"]
        textAPI["Chat API<br/>[Component: FastAPI]<br/>Nhận text"]
        audioAPI["Audio Upload API<br/>[Component: FastAPI]<br/>Nhận file ghi âm"]
        voiceAPI["Realtime Voice API<br/>[Component: FastAPI HTTP / WS]<br/>Nhận audio trực tiếp"]
        chatProcessor["Chat Processing<br/>[Component: Python / DeepAgents]<br/>ASR nếu cần, context và trả lời"]
        voiceProcessor["Realtime Voice Processing<br/>[Component: Python / Google Gen AI]<br/>Phiên voice, audio và lượt thoại"]
        toolIntegration["Tool Integration<br/>[Component: Python / MCP client]<br/>Gọi tool — xem hình 3.3"]
    end
    geminiService["Google Gemini API<br/>[External Software System]<br/>LLM và Gemini Live"]
    customerMemory[("Customer Memory Store<br/>[Container: Markdown / filesystem hoặc S3]")]
    conversationDB[("Application Database<br/>[Container: PostgreSQL / Neon]")]

    chatUI -->|"HTTPS: text; JSON/SSE"| textAPI
    chatUI -->|"HTTPS: file; JSON/SSE"| audioAPI
    chatUI -->|"HTTPS: tạo phiên; WSS: audio"| voiceAPI
    textAPI -->|"Xử lý lượt text"| chatProcessor
    audioAPI -->|"Xử lý lượt ghi âm"| chatProcessor
    voiceAPI -->|"Quản lý phiên voice"| voiceProcessor
    chatProcessor -->|"HTTPS: phân tích / trả lời"| geminiService
    voiceProcessor -->|"WSS: audio / transcript"| geminiService
    chatProcessor -->|"Nạp / cập nhật memory"| customerMemory
    voiceProcessor -->|"Nạp / cập nhật memory"| customerMemory
    chatProcessor -->|"SQL: lưu Chat của account"| conversationDB
    voiceProcessor -->|"SQL: lưu journal Voice"| conversationDB
    chatProcessor -->|"Tra cứu / thao tác đã xác nhận"| toolIntegration
    voiceProcessor -->|"Tool chỉ đọc"| toolIntegration

    classDef component fill:#1168bd,color:#fff,stroke:#0b4884;
    classDef container fill:#438dd5,color:#fff,stroke:#0b4884;
    classDef external fill:#666,color:#fff,stroke:#444;
    class textAPI,audioAPI,voiceAPI,chatProcessor,voiceProcessor,toolIntegration component;
    class chatUI,customerMemory,conversationDB container;
    class geminiService external;
    style chatBackend fill:transparent,stroke:#1168bd,stroke-width:2px;
```

Chat Processing gom điều phối lượt, ASR, context, DeepAgent và adapter liên quan. Realtime Voice Processing gom SessionManager, Controller, Gemini Live adapter và các phần dùng chung. API kiểm tra session/role hoặc API key theo chế độ; Voice còn kiểm tra owner token/ticket. Voice không chạy DeepAgent cho từng audio chunk.

**Customer Memory Store** lưu thông tin học được để dùng lại qua nhiều cuộc gọi. **Application Database** lưu dữ liệu nghiệp vụ và transcript/checkpoint/journal để xem lại; cũng là database ở hình 3.1 và 3.3.

### 3.3. MCP tools và Catalog API

Tool Integration ở hình 3.2 gọi một trong ba MCP server. Catalog API phục vụ giao diện đọc sản phẩm trực tiếp từ PostgreSQL.

```mermaid
flowchart LR
    productUI["Web UI<br/>[Container: React]"]
    subgraph toolsBackend["Backend — Container: Python / FastAPI"]
        catalogAPI["Catalog API<br/>[Component: FastAPI / SQLAlchemy]<br/>Danh sách / chi tiết sản phẩm"]
        toolsClient["Tool Integration<br/>[Component: Python / MCP client]<br/>Nhận lệnh từ Chat / Voice"]
    end
    businessMCP["Business MCP Server<br/>[Container: Python / FastMCP]<br/>CRM, catalog, giá, tồn kho, đơn hàng"]
    knowledgeMCP["Knowledge MCP Server<br/>[Container: Python / FastMCP]<br/>Tra cứu chính sách có nguồn"]
    workflowMCP["Workflow MCP Server<br/>[Container: Python / FastMCP]<br/>Callback / handoff"]
    businessDB[("Application Database<br/>[Container: PostgreSQL / Neon]")]
    policyStore[("Knowledge Store<br/>[Container: Pinecone index]")]

    productUI -->|"HTTPS/JSON"| catalogAPI
    catalogAPI -->|"SQL: đọc sản phẩm / tồn kho"| businessDB
    toolsClient -->|"MCP / stdio"| businessMCP
    toolsClient -->|"MCP / stdio"| knowledgeMCP
    toolsClient -->|"MCP / stdio"| workflowMCP
    businessMCP -->|"SQL: đọc/ghi nghiệp vụ"| businessDB
    knowledgeMCP -->|"HTTPS: tìm chính sách"| policyStore

    classDef component fill:#1168bd,color:#fff,stroke:#0b4884;
    classDef container fill:#438dd5,color:#fff,stroke:#0b4884;
    class catalogAPI,toolsClient component;
    class productUI,businessMCP,knowledgeMCP,workflowMCP,businessDB,policyStore container;
    style toolsBackend fill:transparent,stroke:#1168bd,stroke-width:2px;
```

Ba MCP server là ba process con, nằm ngoài khung Backend FastAPI. Workflow hiện trả kết quả callback/handoff; chưa có hàng đợi bền vững hoặc gửi thông báo cho nhân viên. Tool đọc archive memory truy cập repository trực tiếp, không đi qua ba MCP server này.

Các component trong hình là nhóm trách nhiệm có thể bao gồm nhiều class/file; các hình giữ phụ thuộc chính thay vì toàn bộ lời gọi hàm. Các chức năng bên dưới được đối chiếu với code triển khai.

### 3.4. Danh sách component và chức năng

Các API là component tiếp nhận yêu cầu. Bảng này mô tả thêm các component xử lý, tích hợp và lưu dữ liệu phía sau API. Một số được gom trong Chat Processing hoặc Realtime Voice Processing trên sơ đồ để giữ hình dễ đọc.

| Component | Chức năng |
| --- | --- |
| Account & Session Access | Xác minh mật khẩu, tạo tài khoản, lưu/tra phiên đăng nhập và xử lý đăng xuất. |
| Authentication & Authorization | Kiểm tra session, role, Origin hoặc API key để xác định người gọi được phép làm gì; dùng chung giữa các API. |
| Chat Processing | Điều phối từng lượt text/file ghi âm: chuẩn bị ngữ cảnh, gọi agent, cập nhật memory và lưu kết quả của account. |
| Local ASR — trong Chat Processing | Chuyển file ghi âm tiếng Việt thành text tại backend bằng Zipformer/sherpa-onnx. |
| Customer & Turn Context — dùng chung Chat/Voice | Xác định khách, phân tích nhu cầu, nạp CRM/memory, tra cứu dữ liệu cần thiết và dựng bản tóm tắt ngữ cảnh CallBrief. |
| DeepAgent — trong Chat Processing | Dùng ngữ cảnh và các tool được cấp quyền để sinh câu trả lời tư vấn. |
| Realtime Voice Processing | Quản lý phiên microphone, trao đổi audio/transcript, xử lý ngắt lời, gọi tool chỉ đọc và hoàn tất lượt Voice. |
| LLM / Gemini Live Adapters | Kết nối mô hình AI: gửi nội dung để phân tích/sinh câu trả lời hoặc trao đổi audio realtime với Gemini Live. |
| Tool Integration | Khởi chạy/kết nối MCP, giữ danh sách tool, áp dụng quyền theo lượt/kênh và chuyển yêu cầu đến công cụ phù hợp. |
| Customer Memory Access & Persistence — dùng chung Chat/Voice | Đọc thông tin đã học của khách, phối hợp khóa ghi và commit cập nhật vào filesystem hoặc object storage. |
| App Data Repository | Đọc/ghi tài khoản, session, hội thoại, tin nhắn, checkpoint và feedback trong PostgreSQL theo chủ tài khoản. |
| Salesman History Reader | Tìm và đọc transcript, CallBrief, memory snapshot đã lưu; cung cấp dữ liệu cho màn hình Salesman. |
| Voice Journal Repository — trong luồng Voice | Lưu transcript từng lượt, trạng thái commit, batch memory chờ xử lý và snapshot để xem lại hoặc hỗ trợ phục hồi ghi memory. |
| CRM / Catalog Data Access | Tra hồ sơ khách, lịch sử đơn, sản phẩm, biến thể và tồn kho từ database nghiệp vụ. |

Account & Session Access và Authentication & Authorization là các nhóm trách nhiệm của module auth cùng repository, không phải hai service triển khai riêng. Customer Memory Access & Persistence là phần xử lý đọc/ghi; **Customer Memory Store** là nơi chứa dữ liệu. Tương tự, repository truy cập **Application Database**, không phải chính database.

#### Các MCP server hỗ trợ

Ba server dưới đây là process riêng bên ngoài Backend FastAPI; chức năng của chúng được tách rõ ở hình 3.3.

| Server | Chức năng |
| --- | --- |
| Business MCP Server | Cung cấp tool tra CRM, catalog, tồn kho, báo giá; tạo, theo dõi và cập nhật đơn hàng. |
| Knowledge MCP Server | Tìm chính sách liên quan, lọc tài liệu nội bộ/hết hạn và trả thông tin kèm nguồn. |
| Workflow MCP Server | Kiểm tra/điều chỉnh lịch gọi lại và tạo kết quả handoff; hiện chưa có hàng đợi hoặc gửi thông báo thực tế. |

Căn cứ: [`auth.py`](../src/telesale_agent/entrypoints/api/auth.py), [`deepagent/turn.py`](../src/telesale_agent/application/deepagent/turn.py), [`realtime/controller.py`](../src/telesale_agent/application/realtime/controller.py), [`customer_context.py`](../src/telesale_agent/application/customer_context.py), [`memory/coordinator.py`](../src/telesale_agent/application/memory/coordinator.py), [`adapters/db`](../src/telesale_agent/adapters/db), [`mcp_servers`](../src/mcp_servers).

### 3.5. Các component API và endpoint

Các component này nhận request, kiểm tra đầu vào và gọi các bộ phận xử lý tương ứng ở mục 3.4.

| Component | Endpoint hiện có | Chức năng |
| --- | --- | --- |
| Auth API | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | Quản lý tài khoản và phiên đăng nhập. |
| Catalog API | `GET /api/catalog/products`, `GET /api/catalog/products/{sku}` | Đọc danh mục, biến thể và tồn kho từ PostgreSQL. |
| Chat API | `POST /api/chat` | Nhận text; trả JSON hoặc SSE theo request. |
| Audio Upload API | `POST /api/chat/audio` | Nhận file ghi âm và chuyển vào pipeline Chat có ASR local. |
| Realtime Voice API | `GET /api/voice/capabilities`; `POST /api/voice/sessions`; `GET`, `DELETE /api/voice/sessions/{session_id}`; `WS /api/voice/sessions/{session_id}/stream` | Kiểm tra khả năng Voice, quản lý phiên và trao đổi audio/events. |
| Conversation API | `POST`, `GET /api/conversations`; `GET /api/conversations/{conversation_id}`; `POST /api/conversations/{conversation_id}/end` | Quản lý hội thoại thuộc tài khoản đang đăng nhập. |
| Feedback API | `PUT`, `DELETE /api/messages/{message_id}/feedback` | Lưu hoặc xóa đánh giá/góp ý cho một câu trả lời. |
| Salesman API | `GET /api/salesman/conversations`, `GET /api/salesman/conversations/{source}/{conversation_id}` | Tìm và đọc bản lưu Chat/Voice, brief và memory snapshot. |
| System API | `GET /`, `GET /health`, `GET /api/health`; `DELETE /api/sessions/{conversation_id}` | Health check; xóa state phiên guest trong RAM. |

