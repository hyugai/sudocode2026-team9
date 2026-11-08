# SUDO CODE · Synee AI storefront

Next.js 16 / React 19 frontend migrated from Telesale Hub to the approved Synee AI Figma design. Existing text/audio API contracts are retained.

```sh
npm ci
# Optional: copy .env.example to .env.local and set your public backend URL.
npm run dev
```

The default backend is `http://localhost:8000` in development and `https://telesale-agent-api-3no2.onrender.com` in production. `NEXT_PUBLIC_API_BASE_URL` overrides it. Never put API keys in public environment variables. The backend must allow the frontend origin through CORS.

The storefront list and product detail pages now request `/api/catalog/products` and `/api/catalog/products/{sku}` from the backend. Those endpoints read products, variants and effective stock from PostgreSQL via `DATABASE_URL`. The web does not need a database credential. If the catalog API is unavailable, the list shows an error instead of substituting snapshot data.

Each of the 40 current catalog SKUs maps to its own distinct local WebP illustration in `utils/product-illustrations.ts`. Cards and product details use the same image for that product. Mini/Pro models, air fryers, shoes, pumps, strollers and replacement filters have different physical designs. The catalog regression verifies unique image paths and SHA-256 hashes, preventing shared files or renamed duplicates. Images in `public/products/illustrations/` are labelled **Ảnh minh họa** and do not represent official model photographs or exact variant colors. Unknown SKUs and failed image loads retain a text fallback. These display assets never replace API product data. Generation prompts and provenance are recorded in [`docs/design/product-illustrations.json`](../../docs/design/product-illustrations.json).

The `data/*.json` files are retained only for the separate demo cart and checkout flow. After changing the source BTC catalog used by that demo, copy the three JSON files from `dataset/BTC-Data-Vong1-TEAMS/catalog/` into `src/web/data/` and run `node --experimental-strip-types --test tests/catalog.test.mjs` to check they match.

```sh
npm test
npm run lint
npx tsc --noEmit
npm run build
```

If Turbopack cannot start its CSS worker on Windows or in a restricted environment, use `npm run build -- --webpack` (or `npm run dev -- --webpack`).

The product list and detail pages use the PostgreSQL catalog, including variant prices and effective stock. Product detail purchase buttons are hidden until cart pricing is connected to the same catalog. Cart, checkout, receipts and tracking remain a separate local demo adapter; orders and payments are not connected. Login/register now use the backend auth API; account history, compact call briefs and per-reply feedback persist in PostgreSQL.

The storefront and product detail pages load product identity, prices, variants and stock from the backend's `/api/catalog/products` endpoints backed by PostgreSQL/Neon. If the catalog is unavailable, the UI shows an error instead of silently substituting demo products. The default production API is `https://telesale-agent-api-3no2.onrender.com`; set `NEXT_PUBLIC_API_BASE_URL` to override it for both catalog and chat/voice.

The separate cart, checkout, receipts and tracking routes still use an explicitly labeled local demo adapter and bundled BTC snapshots in `src/web/data`. Product detail pages do not submit live catalog items to this demo checkout. Live orders and payments are not connected. `/account` shows the authenticated user and `/account/conversations` opens saved conversations; guest consultation remains available without login.

Text chat and audio uploads share a conversation ID. Account conversations save messages, the latest compact brief and a backend checkpoint; the last opened ID restores after reload. The history page can open earlier conversations. Guest messages/drafts retain their existing current-tab storage; raw audio stays in memory. Ending an account conversation keeps its history; the old session DELETE endpoint remains for guests.

The header's **Tài khoản** button toggles a compact menu directly below the button, with links to personal profile, orders and conversation history. The menu closes on outside click, Tab to another area, Escape, repeat click or navigation; Escape restores focus to the trigger and Arrow Down focuses the first link. Profile links open `/account`. Logout revokes the session and clears browser account state. Login/logout or an account switch remount private state; guest history is never imported into an account. Phone changes start a fresh conversation and retain saved account history.

### Account API configuration

Set `API_BACKEND_URL=http://127.0.0.1:8000` in `src/web/.env.local` for the server-side `/api/:path*` rewrite. Set `WEB_ORIGIN=http://localhost:3000` and `SESSION_TTL_DAYS=7` on the backend. On deployment use the actual HTTPS web origin and reachable backend URL, then rebuild/restart Next.js. HTTPS origins default to Secure cookies. `NEXT_PUBLIC_API_BASE_URL` still configures catalog, guest chat and native realtime voice; it does not replace the auth proxy target. Never put database credentials or an API key in public variables.

Logged-in replies support positive/negative ratings and text comments. Feedback is saved by database message ID and restored with history. Guest replies and the initial greeting have no persistent feedback controls. Only a successful API response confirms a save. See [IMPLEMENTATION.md](../../IMPLEMENTATION.md) for setup and the API-only demo checks; no UI tests were run for this change at the user's request.

The dashboard's dark chatbot hero fills at least the first viewport, accounting for the fixed header on desktop and mobile. Desktop navigation aligns the logo, centered search and cart/account/support in one 88px row; mobile retains two rows. **Khám phá sản phẩm** sits near the bottom of the hero, after the centered chat content. Product browsing starts below the fold. Short viewports can scroll through the hero without clipping controls. The background uses the official React Bits **Cubes** component, with an 18×18 grid on desktop and 12×12 at widths up to 760px, cursor tilt, automatic animation, intro and click ripples. Slightly brighter navy faces (`#0c172b`), blue-grey edges (`#4b6282`) and cyan ripples retain the dashboard palette. The shared cube geometry uses one instanced draw per frame with opaque faces; more cubes still increase per-frame simulation and geometry work. Pointer events never intercept chat controls or scrolling; reduced motion disables motion and ripples, and unavailable WebGL2 uses a static background. Animation pauses outside the visible hero or hidden tab, backing buffers are capped at 2048px per edge, and GPU resources are released on unmount. Source, license and integration notes are in `app/components/cubes/UPSTREAM.md`.

The dashboard's top chatbot opens `/ai-chat` when sending text, selecting an audio file, or choosing **Voice**. The dashboard and workspace expose exactly two modes: **Chat** and **Voice**. Chat accepts text or an audio attachment in the same composer. The microphone upload icon opens the audio file picker ("Tải file audio"); Voice starts the realtime flow. Sending audio uses `/api/chat/audio`, which runs the existing ASR/conversation pipeline and displays the returned transcript in the shared message history; text uses `/api/chat`. Selecting a recording opens Chat for preview and explicit submission. Legacy `?mode=offline` links also open Chat. Dashboard submissions start once in the shared provider before client navigation; refresh and Back never replay a send. Drafts, selected files, customer phone and product context survive client navigation. If the backend is unavailable, sending stays disabled with an explanation and drafts are retained until manual submission when ready.

The workspace includes current-tab transcript search, message copy, text export, consultation profile/context, and confirmed creation of a new conversation. It displays actual session data rather than the design's demo conversations, account or simulated replies. The history page links back to the workspace; diagnostic logs remain in `/account/conversations`.

Realtime mode embeds the existing voice client and LiveKit Wave directly in the workspace. It checks `/api/voice/capabilities` and starts microphone capture only after **Bắt đầu trò chuyện** is pressed. Changing workspace mode or leaving the page releases the microphone, audio context, WebSocket and voice session; text/recording submission remains disabled during an active call. Floating commerce chat retains its shared voice dialog. Voice uses its own backend session and preserves mute, interruption, resampling and buffered playback from this branch. See [Gemini Live setup](../../docs/deployment/gemini_live.md) for backend configuration.

The voice dialog uses the [LiveKit Agents UI Wave](https://docs.livekit.io/reference/components/agents-ui/component/agent-audio-visualizer-wave/) with `size="xl"`, `color="#00ff26"`, `colorShift={2}` and `lineWidth={6}`. It takes explicit `state` and `volume` from the existing voice client rather than `useAgent()`, which requires a LiveKit session. No room/token service is needed. Playback volume is measured from the rendered PCM samples at up to 20 Hz; buffered audio keeps the speaking state until playback finishes or is interrupted. Reduced motion and unavailable WebGL use a static wave. Upstream source and licenses are documented in [components/agents-ui/NOTICE.md](components/agents-ui/NOTICE.md).

Browser regressions in `tests/*browser.mjs` and `tests/browser-check.mjs` use a separate headless Chromium instance exposing `CDP_URL` (default `http://127.0.0.1:9222`). Set `BASE_URL` to the running frontend and `BROWSER_ARTIFACT_DIR` to an output folder. Run `node tests/voice-browser.mjs` for the realtime voice integration, Wave states and reduced-motion fallback with mocked microphone, audio and backend services.

Run `node tests/ai-chat-browser.mjs` for dashboard-to-workspace navigation, duplicate prevention, shared text/audio identity, upload preview/removal, retries, cooldowns, transcript search, reload continuity, inline LiveKit controls, microphone cleanup, mobile drawers and 320px layouts. APIs, microphone and audio devices are mocked. Screenshots default to `outputs/debug/streaming-ui/ai-chat/` at the repository root. Live backend/ASR/Gemini voice verification requires the configured services.

Run `node tests/account-menu-browser.mjs` for the anchored account menu, outside-click and keyboard dismissal, profile validation/save, confirmed identity changes, orders/history links, and desktop/mobile screenshots in `outputs/debug/streaming-ui/account-menu/`. This suite uses synthetic guest data and mocked health checks.

### Call brief sidebar

The dedicated Chat workspace displays the pipeline's compact call brief: summary, needs, objections and unresolved issues. The same panel opens as a drawer on mobile. Profile and selected-product controls remain under the collapsed **Thông tin phiên** section. Voice keeps its existing full-screen layout.

Both `POST /api/chat` and `POST /api/chat/audio` return a top-level `call_brief` containing the four compact display fields, independently of `ENABLE_DEBUG_RESPONSE`. The response masks supported PII patterns and does not serialize customer identifiers or raw CRM/memory objects into this field. Full diagnostic data stays behind the existing debug setting. The frontend still accepts `debug.call_brief` from older backends for compatibility.

The pipeline refreshes the brief locally after current-turn facts are persisted, without another LLM, ASR, retrieval or database freshness call. Current-turn facts take priority in the compact display, so budget/room corrections are visible in the same response. See the [Vietnamese Call Brief demo guide](../../docs/deployment/call_brief_demo.md) for startup commands, text/audio scenarios and Network verification with debug disabled.

Without brief data the panel shows an empty state. A successful reply updates the brief; a failed request keeps the last brief and labels it as the prior version. Account brief previews restore from PostgreSQL with the saved conversation. Guest briefs stay in memory and clear on reset/reload; they remain excluded from guest sessionStorage, raw audio and transcript exports. Reload never automatically sends a chat turn.

For catalog integration checks without a database, start `node tests/catalog-fixture.mjs` (localhost port 8100), point the frontend's `NEXT_PUBLIC_API_BASE_URL` to `http://127.0.0.1:8100`, then run `node tests/live-catalog-browser.mjs`. This verifies API-backed prices, product consultation, catalog outages and the LiveKit dialog. The legacy purchase browser suites target the original demo product pages; live product pages deliberately do not expose demo purchase actions. Unit contract probes also require Python 3.11+; set `PYTHON` to a virtual environment's executable when needed.
