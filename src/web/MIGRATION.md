Synee AI frontend migration
===========================

The approved Figma file is the visual reference:
https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=23-1049

The existing `utils/chat-api.ts` remains unchanged and is the API contract source.
No backend, dataset, Figma, or production service was modified.

| Feature | Legacy implementation | Synee destination | Migration |
| --- | --- | --- | --- |
| Text chat | JSON POST `/api/chat` | Shared `ChatPanel` | Same request/response normalization |
| Audio | Multipart POST `/api/chat/audio` | One paperclip upload control | Same fields, preview/removal, limits and manual retry |
| Session/history | React memory + generated UUID | `useConversation` above A/B/C | One client, messages, draft, file, phone and ID |
| Customer phone | Header field | Account/conversation dialog | Same request field; starts empty instead of identifying everyone as the legacy example customer |
| Readiness | GET `/health` | Composer status | Same polling, disabled send and recovery |
| Errors/rate limits | `ChatApiError`, HTTP 429 | Inline/compact status | Same cooldown and duplicate lock; no automatic POST retry |
| Debug logs | Separate tab | Menu → Nhật ký hội thoại | Intent, RAG, optional planner steps and complete debug payload |
| Analytics | “Soon” placeholder | Menu | Still disabled |
| Catalog/search | None | Figma catalog | Explicit demo data, local filtering, no invented API |
| Authentication | No login client | Resume/account dialog | Explains unavailable authentication; no fabricated login |
| Streaming | None; complete JSON responses | Loading state | No invented SSE/WebSocket stream |

Interaction and state
---------------------

- `IntersectionObserver` watches the complete inline wrapper with threshold 0,
  viewport root, and zero root margin. Partial intersection keeps A. Only complete
  absence permits the floating launcher (B) or compact panel (C).
- The inline wrapper stays in document flow. One chat surface is mounted at a
  time. Shared state and API client stay mounted in `Storefront`.
- B: launcher 56×56, right/bottom 24. C: panel 400×560, right/bottom 24 on desktop.
  Close/Escape returns focus to the launcher. Returning to A closes floating UI
  without stealing focus. Manual open focuses the compact composer.
- Shared history, UUID, draft, audio file/object URL, phone, pending request,
  errors, cooldown and mode survive presentation switching. No request is made
  by opening, closing, scrolling or selecting Voice.
- Voice is labeled as a visual preview. Audio-file upload remains functional and
  separate from live microphone/voice calls. No microphone permission is requested.
- A failed turn preserves input/file for manual retry. A lost response can mean
  the backend already performed actions; the client never automatically retries.
- Product Ask AI fills a normal message with the displayed product name/price;
  it never silently submits or invents a product-context endpoint.
  It is disabled while a request is pending or audio is selected to protect drafts.
- Browser refresh resets client state, as in the legacy app. There is no history
  retrieval endpoint or client login. Customer phone and messages are not written
  to localStorage/sessionStorage. The backend owns its existing in-memory sessions.

Design and responsive adaptations
---------------------------------

- Default desktop: header 104 high; 1200 container; 880×420 inline chat; 650 hero;
  five 224px product cards with 20px gaps. Approved hero copy, Inter typography,
  dark grid, white header, centered 136×36 toggle and layered send controls.
- Single shared chat component handles inline/compact proportions. Default send
  sizes are 132×54 and 88×36; audio/retry/loading labels use enough width to avoid
  clipping. Message history scrolls internally and does not scroll the page.
- Existing upload/status behavior was absent from the static design. Selected
  audio adds a preview/removal row; inline chat grows to 520 high while selected.
  The inline placeholder retains this height when offscreen. Default dimensions
  remain exactly as designed. Errors and readiness messages consume history space.
- Figma supplies no approved mobile breakpoint contract. At narrow widths search
  moves below navigation, categories scroll, the grid uses two/three columns,
  and the compact panel fits the viewport with 16px gutters. Short viewports can
  scroll the chat body to keep the composer reachable. These are implementation
  adaptations; no Figma pages were edited.
- Assets in `public/figma` are downloaded from the Figma MCP design-context
  response, not screenshots. Inter files are self-hosted; see `public/fonts/OFL.txt`.

Configuration and remaining integrations
----------------------------------------

Use `.env.local` with `NEXT_PUBLIC_API_BASE_URL`, following `.env.example`.
Legacy defaults remain localhost:8000 in development and the existing Render URL
in production. The public URL must not contain credentials. No dependencies added.

The backend optionally requires `X-API-Key` if `API_KEY` is configured. The legacy
browser client has no safe credential transport. This migration does not expose
that secret or bypass authentication. Such deployments need an approved server-side
gateway/authentication arrangement; otherwise 401 is shown as a normal error.
Backend CORS must allow the deployed frontend origin.
The backend also exposes DELETE `/api/sessions/{conversation_id}`; the legacy
frontend did not call it, so this migration adds no destructive session-reset UI.

Cart, checkout, real inventory, order tracking, login, history recovery and live
voice are not connected because no existing frontend service contracts provide
them. The storefront explains their unavailable state. Uploaded duration (120s)
is validated by the backend; the browser preserves the legacy 25 MB size check.

Verification
------------

Run `npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build`.
In restricted environments where Turbopack worker ports are blocked, use the
supported `npm run build -- --webpack` fallback. Do not skip TypeScript validation.

The optional browser suite uses Node 24's built-in WebSocket and an installed
Chromium-compatible browser, with no extra dependency:

```sh
npm run dev
# In a separate terminal, using your installed Chromium executable:
chromium --headless --remote-debugging-port=9222 --user-data-dir=/tmp/synee-browser about:blank
# In another terminal:
node tests/browser-check.mjs
```

`CDP_URL`, `BASE_URL` and `BROWSER_ARTIFACT_DIR` override defaults. The browser
suite mocks only backend fetches inside the test browser; it never sends live
chat POST requests. It checks real React behavior, A/B/C dimensions, centering,
local assets, text/multipart contracts, ID/phone continuity, drafts/files across
modes, rapid submits, failure/retry, cooldown, Voice placeholder, escaped long
replies, debug logs, readiness recovery and 320px layouts. Screenshots and JSON
results default to `/tmp/synee-migration/`. Real ASR/LLM execution requires the
backend, models, providers and credentials; those are not replaced by these mocks.
