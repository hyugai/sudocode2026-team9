# M3 verification

**Final verdict: FAIL — M3 is not ready for sign-off or progression to M4.**

The storefront's guest/demo flows and high-impact visual feedback mostly work.
Essential customer authentication, authenticated profile/history, real commerce,
and customer authorization are absent or unverified. Passing mocked tests does
not close those gaps. Isolated probes also reproduce conversation-ownership and
phone-identity trust weaknesses in the actual backend handler/resolver code.

## Audit scope and evidence

- Date: 2026-10-26, Asia/Ho_Chi_Minh. Base commit: `908f924`, with the existing
  uncommitted feedback/purchase implementation included in the audited worktree.
- Repository root: `/home/cookies/repos/sudocode2026-group_9`.
- Frontend: `src/web`. HTTP backend:
  `src/telesale_agent/entrypoints/api/chat.py`; internal tools:
  `src/mcp_servers/mcp_db.py` and `src/mcp_servers/tools/`.
- Actual catalog path from this CWD: `../../dataset/BTC-Data-Vong1-TEAMS/catalog/`,
  rather than `../dataset/`. Reference date: **2026-10-15**, not live inventory.
- Read the text and rendered screenshots/annotations of all eight PDF pages.
  PDF SHA-256:
  `3e3eacddb196acd8f4697300a31e5a38f60c8cd15bcb13b1b281e7384c18ebe4`.
- Figma inspected read-only through MCP: [approved PDP](https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=143-334),
  cart `145:304`, [checkout](https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=145-365),
  review `145:450`, success `145:514`. PDP/checkout renders and purchase structure
  were compared with fresh browser screenshots. No design was changed.
- This pass adds only this report and non-destructive instrumentation:
  `tests/m3-security-contracts.test.mjs` and `tests/m3-browser.mjs`.
  No application feature, backend contract or source dataset was modified.
  Fingerprints of the inspected backend/bootstrap/MCP files and catalog JSON
  inputs remained unchanged.

### Local configuration and connectivity

The repository's Linux `.venv`, root `.env`, `web/.env.local`, and `models/` are
absent. The inspected process has no configured service/LLM/Pinecone/database
credentials, API-base override, CORS override, or debug-response flag. Only
presence was checked; no credentials or private customer records were printed.
Python lacks FastAPI, Pydantic, Uvicorn and the voice-test dependencies.

The default browser client points to `http://localhost:8000` in development and
the existing Render URL in production. Read-only probes found:

| Probe | Actual result | Meaning |
| --- | --- | --- |
| Local storefront, port 3000 | HTTP 200 | Frontend is reachable. |
| `http://127.0.0.1:8000/health` | HTTP 000, connection refused | No reachable local backend on the configured port. |
| Configured legacy deployment `/health` | HTTP 000, curl timeout after 15 seconds | Unreachable from this verification host; its deployment state is undetermined. |
| Unmocked browser | Readiness unavailable; populated draft retained; send disabled | Correct unavailable-state handling, **not** a successful live chat transaction. |

No real chat/audio POST, session DELETE, order, payment, customer lookup or
customer-memory mutation was sent to the deployment. Deployment authentication,
database contents and CORS settings could not be verified remotely.

## 1. Feature-to-endpoint verification

Types: **REAL API** = client wired to an existing HTTP contract, whether or not
live execution could be verified; **LOCAL ONLY** = browser/bundled-data behavior;
**MOCK** = explicitly simulated operation/test response; **UNAVAILABLE** = no
supported implementation. A REAL API classification alone is not a passing test.

| Feature | Frontend | Backend endpoint | Integration type | Test | Result |
| --- | --- | --- | --- | --- | --- |
| Registration | Disabled with explanation | None | UNAVAILABLE | Source inventory; mocked and unmocked account UI | **FAIL essential integration**; no account is created. |
| Login | Disabled; no password/credential form | None | UNAVAILABLE | Same; no invented auth request | **FAIL essential integration**. |
| Authenticated logout | Disabled; conversation ending is a different action | None | UNAVAILABLE | Account UI and handler inspection | **FAIL**; no authenticated session to revoke. |
| Session expiry/refresh | Guest UUID restored from browser storage | None for customer sessions/refresh | UNAVAILABLE | Auth inventory; synthetic 401/403 failures | **FAIL/not testable** as customer authentication; a service-key denial is not token expiration. |
| Profile retrieval | `/account` edits an unverified guest phone hint | No customer/profile HTTP route | LOCAL ONLY | Profile form, consent and reload checks | **PASS guest UI; FAIL authenticated profile retrieval**. |
| Account sidebar | Profile, demo orders, history, disabled auth | None needed for presentation | LOCAL ONLY | 22 feedback checks; eight unmocked checks | **PASS UI**, including unique IDs, Escape/focus return and 320px fit. |
| Customer-specific data isolation | Tab-local receipts/history; browser-wide guest cart | No principal/ownership API | UNAVAILABLE | Synthetic handler/resolver probes; independent-tab receipt test | **FAIL authorization**. Independent tab storage is not authenticated ownership. |
| BTC catalog and filtering | Bundled, unchanged BTC product records | No public catalog HTTP route; internal MCP tools exist | LOCAL ONLY | Four catalog cases; 14 category checks | **PASS snapshot**, not live catalog integration. |
| SKU-specific PDP/navigation | All 40 exact parent SKU routes; unknown SKU 404 | None | LOCAL ONLY | 19 card/PDP checks, all 40 routes fetched | **PASS**. Product images remain honest placeholders. |
| Variants, price, stock, quantity | Exact variant SKU/base-price delta; dated inventory timeline; bounds | No public live quote/stock endpoint | LOCAL ONLY | Commerce and purchase suites | **PASS dated BTC behavior**; live price/availability not verified. |
| Cart create/read/update/delete | Browser store; header count; local persistence | None | LOCAL ONLY | Merge/update/remove, totals, reload and invalid storage cases | **PASS guest cart**; no server cart or customer binding. |
| Checkout/shipping/payment selection | Validated address, policy-based fees, COD/bank/wallet choices | None public | LOCAL ONLY | Address/COD/remote-bulky/fee cases; mobile form and keyboard | **PASS demo selection/calculation**; no address verification or live quote. |
| Order confirmation/creation | Explicit review and consent, pending lock and replay token | Internal MCP `order.create`, not a browser HTTP contract | MOCK | Repeated submission, failures/manual retry and multi-SKU cases | **PASS local demo only; FAIL real order integration**. |
| Order success/history/details | DEMO receipt in SessionStorage, unpaid | No order/status/history HTTP route | LOCAL ONLY | Exact receipt, unknown order and independent guest tab | **PASS demo UI; FAIL authenticated order history/ownership**. |
| Payments and carrier tracking | No charge; future carrier stages explicitly not occurred | None public | MOCK | Online failure, unpaid receipts and tracking checks | **UNAVAILABLE live**; no payment/fulfillment success verified. |
| Chat readiness | Existing readiness poll | `GET /health`; root `GET /` also exists | REAL API | Actual health probes; unmocked browser | **FAIL live availability from this host**; unavailable UI passes. |
| Text/contextual consultation | Existing JSON body, explicit SKU context, no automatic send | `POST /api/chat` | REAL API | Client contracts and mocked browser turns | **PASS client/MOCK tests; live processing BLOCKED**. |
| Chat streaming | Typing indicator, then whole JSON response | No streaming/SSE/WebSocket endpoint | UNAVAILABLE | Server return shape and `response.json()` client inspection | **NOT IMPLEMENTED**. Typing animation is not streaming. |
| Conversation restoration | Messages/draft/UUID/mode/context restored in same tab | No GET history/restore endpoint | LOCAL ONLY | Reload, navigation, invalid schema and identity-change consent | **PASS local restoration**, not server/cross-device restoration. |
| End current conversation | Explicit confirmation; retain history on failure | `DELETE /api/sessions/{conversation_id}` | REAL API | Mocked 401/403/503/network/wrong-receipt cases; isolated real handler | **PASS client handling; live DELETE unverified; ownership FAIL**. |
| Audio upload | One upload icon, preview/removal, multipart, same UUID | `POST /api/chat/audio` | REAL API | Real browser WAV preview; mocked multipart/transcript/failure tests | **PASS client/local decoding; real ASR processing BLOCKED** by unavailable backend/dependencies/weights. |
| Loading/validation/empty/failure | Readiness, pending, field errors, manual retry, empty cart, missing SKU/order | Existing chat error/status contracts; local demo scenarios | LOCAL ONLY | Existing suites plus unmocked unavailable-state checks | **PASS tested UI states**. Mock errors are not production failure evidence. |

The HTTP route inventory is exactly: `POST /api/chat`, `POST /api/chat/audio`,
`DELETE /api/sessions/{conversation_id}`, `GET /`, `GET /health`. Internal CRM,
catalog, inventory and order functions are **not** additional public endpoints.
They were neither exposed nor called directly by this audit.

## 2. Feedback UI verification

| Feedback item | PDF page | Status | Evidence |
| --- | --- | --- | --- |
| Login/register/logout | 1 | **BLOCKED, essential** | All three controls explicitly disabled; no backend auth contract. Honest disclosure does not complete the feature. |
| Account/profile page | 1 | **PARTIAL** | `/account` is a guest consultation form, not a retrieved authenticated customer profile. |
| Sidebar with profile/orders/history/logout | 1–2 | **UI DONE; auth/data PARTIAL** | `account-content.tsx`, native drawer; 22 feedback checks. Orders/history remain demo/tab-local and logout unavailable. |
| Staff/salesman workspace | 1 | **DEFERRED** | Explicitly outside this pass; no role/workspace contracts. Not counted as a delivered feature. |
| Remove duplicate category-menu entries | 2 | **DONE** | Category-only links; account/history/orders grouped in account; header search/cart/account retained. |
| Clearer grouping/headings/category selections | 2–3 | **MOSTLY DONE** | White outlined category block and visible selected state; category geometry/keyboard tests pass. Unsupported sales/newest sorting remains disabled rather than invented. Full decorative restyling is deferred. |
| PDP blocks and action alignment | 4 | **DONE for requested cleanup** | White information surface; aligned purchase actions; simpler secondary Ask action. Desktop and 320px screenshots reviewed. |
| Shipping/payment choices stand out | 4–5 | **DONE UI** | Bordered full-width option cards, selected outline/background; labeled native radios. This does not verify delivery/payment providers. |
| Recipient/delivery/payment grouped on review | 5 | **DONE** | One receipt/address section with adjacent labels and values; review screenshot and functional checks. |
| Remove confusing no-retry sentence; visible back action | 5 | **DONE** | Clear demo/payment explanation; “Quay lại chỉnh sửa” above the confirmation content. |
| Continue-shopping only on cart/success | 5 | **DONE** | Conditional rendering only for those two views; checkout/review checks pass. |
| Order-success information hierarchy | 5–6 | **DONE UI; demo only** | Grouped success banner, DEMO ID, received/unpaid status and details link; no claim of a live order. |
| Contextual Synee panel beside PDP | 6 | **DONE UI** | Desktop separate column; mobile stacked panel; exact SKU context/draft retained, no automatic send; close returns focus. |
| Working “Xem tất cả” | 6–7 | **DONE** | Resets filters and navigates to `#catalog-heading`; full 40-item result verified. |
| Remove ordinary search because AI exists | 7 | **NOT ADOPTED, intentional** | Latest requirements retain direct SKU/text search; verified without sending a chat turn. |
| Taller/full-screen hero; decorative button overhaul | 8 | **DEFERRED, optional** | A/B/C behavior and primary send styling preserved. Secondary PDP Ask action simplified; no broad redesign. |

### Remaining design inconsistencies

- The older Figma checkout/review components still contain continue-shopping
  links and prototype text controls. The website intentionally follows the
  newer PDF feedback for these items. No Figma synchronization was authorized.
- Figma PDP `143:334` includes separate shipping and applicable-policy sections.
  Current `app/components/product-detail.tsx:72` renders description/specifications
  only. Checkout exposes fee rules, but pre-purchase policy parity is incomplete.
  Record this for M3 follow-up; no product/promotion claims were invented to fill it.
- Actual photography/gallery navigation cannot be verified: BTC supplies no
  product photos. Placeholder honesty is correct; a placeholder is not a finished
  photo gallery.
- Keyboard, focus, wrapping and viewport checks passed in Chromium. No complete
  screen-reader audit, full WCAG conformance certification, exhaustive visual
  diff or native Figma prototype-playback audit was performed.

## 3. Executed tests and results

| Command/check | Actual outcome | Evidence/qualification |
| --- | --- | --- |
| `npm test` | **PASS**, five test files | Current runner reports file-level results. Direct runs below verify named cases. |
| `node --experimental-strip-types tests/{catalog,chat-api,commerce,conversation-session}.test.mjs` (each separately) | **26 PASS**: 4 + 7 + 10 + 5 | BTC mappings, API bodies/errors, commerce arithmetic/state machine and guest restoration. Chat/provider calls are mocked. |
| `node --experimental-strip-types tests/m3-security-contracts.test.mjs` | **5 diagnostic assertions PASS** | Reproduces security findings using selected real source functions with stub services and synthetic records. This is **not a security-control PASS** or an HTTP/live backend test. |
| `node tests/feedback-browser.mjs` | **22 PASS** | Account, reload/context, review/success, profile consent, tab-local receipt isolation, focus and mobile. Service responses explicitly mocked. |
| `node tests/purchase-browser.mjs` | **33 PASS** | Variants, cart CRUD/persistence, multi-line prices, fees, COD, explicit review, failures/manual retry, repeated confirmations and DEMO receipts. |
| `node tests/product-card-browser.mjs` | **19 PASS** | All 40 SKU routes, exact information, keyboard navigation, 404, search and audio continuity. |
| `node tests/category-browser.mjs` | **14 PASS** | All parent/subcategory SKU sets, reset/search and 320px keyboard navigation. |
| `node tests/browser-check.mjs` | **33 PASS** | Homepage A/B/C, signature control geometry, actual browser WAV decoding, text/audio contracts, escaped replies, 429/network recovery and short mobile viewport. Backend replies mocked. |
| `node tests/m3-browser.mjs` | **8 PASS, NO API MOCKS** | Actual unavailable readiness, disabled send with retained draft, guest account states, 320px drawer, missing DEMO order and exact BTC PDP. Only health GETs; no service mutation. |
| `npm run lint` | **PASS** | Includes both new instrumentation files. |
| `npx tsc --noEmit` | **PASS on serialized rerun** | Initial run overlapped build regeneration and saw missing generated `.next/types` files (TS6053). Rerun after completed build has no source type errors. |
| Restricted `npm run build` | **FAIL: environment** | Turbopack/PostCSS worker cannot create/bind a local port, `EPERM`; not a reported CSS syntax/type defect. |
| Approved build, original cache | **FAIL: cached EPERM** | Replayed the restricted failure. Cache preserved at `/tmp/m3-turbopack-cache-1793009095`. |
| Approved clean-cache `npm run build` | **PASS** | Compiled, typed and generated 50 pages including both account routes and all 40 PDPs. No application or CSS workaround was applied. |
| Socket diagnostic | **Restricted denied / approved allowed** | Independently confirms local socket permissions differ, supporting the environment diagnosis. |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ../../tests -p 'test_voice_input.py' -v` | **BLOCKED / exit 1** | Import fails on missing `numpy`; FastAPI/Pydantic/Uvicorn are also absent. Zero backend functional cases executed. No model/provider processing verified. |
| Secret-pattern scan | **No matches in 37 source/build files scanned** | Known service-key/private-key/credential-URL patterns, counts only; not an exhaustive secret or dependency audit. |
| `git diff --check`; read-only input fingerprints | **PASS** | No whitespace errors; inspected backend and catalog inputs unchanged. |

Totals: **31 named unit/contract diagnostics pass**, **121 existing browser
checks pass with service mocks**, plus **8 unmocked availability/UI checks pass**.
These numbers are deliberately separate from live integration verification.

The old browser port became unavailable during setup; no application assertion
failed in that attempt. The complete browser sequence subsequently exited 0 in a
fresh isolated profile on port 9223. Tests ran sequentially because they share
guest LocalStorage. No dependencies were installed and no features were changed.

Fresh reports/screenshots:

- `/tmp/synee-m3/evidence/synee-feedback/results.json` and
  `after-pdp-chat.png`, `after-checkout.png`, `after-review.png`, `after-success.png`.
- `/tmp/synee-m3/evidence/synee-purchase/results.json`.
- `/tmp/synee-m3/evidence/synee-product-cards/results.json` (all 40 route results).
- `/tmp/synee-m3/evidence/synee-categories/results.json`.
- `/tmp/synee-m3/evidence/synee-migration/browser-results.json`.
- `/tmp/synee-m3/unmocked/results.json`, `account-desktop.png`, `account-mobile.png`.

To reproduce browser checks, run the local frontend and an isolated Chromium CDP
instance; set `CDP_URL=http://127.0.0.1:9223` for each script above. The unmocked
script specifically verifies the currently unavailable localhost backend; its
expectations must be revised when a real test backend is available. Normal Node
direct runs emit the existing nonfatal module-type inference warning.

## 4. Security findings

| ID / severity | Finding and evidence | Consequence / required remediation |
| --- | --- | --- |
| S1 — **Critical** | No customer principal, login/registration, authenticated logout, refresh/expiry or account ownership contract. Backend route inventory and disabled account controls confirm absence. | Essential M3 identity/access-control requirements fail. Define authenticated customer sessions and server-side ownership checks before exposing private profile/history/orders. |
| S2 — **Critical** | `chat.py:120` selects `sessions[conversation_id]` from the supplied ID; `chat.py:195` deletes it without owner binding. Isolated real-handler probes reuse and delete synthetic A's state when supplied by synthetic B. | Knowing a UUID is treated as access to the session; UUID randomness is not authorization. Bind POST/audio/DELETE to the authenticated owner; test foreign identifiers with HTTP 403/404 in a real isolated API environment. No production exploit was attempted. |
| S3 — **Critical for public customer use** | `adapters/mock/identity.py:21` reads the phone hint, looks up/creates a customer and returns confidence 1.0 without OTP/session proof. `application/customer_context.py:25` then hydrates CRM and memory for that identity. The actual resolver probe trusts a synthetic supplied phone using only a stub DB. | Caller-supplied phone can select a customer context without customer authentication. Real PII exposure was not exercised, but the trust boundary is absent. Separate unverified hints from authenticated identities; authorize CRM/memory/order access server-side. |
| S4 — **High, configuration-dependent** | `chat.py:57` enforces `X-API-Key` only when configured; otherwise accepts anonymous calls. It is a shared service guard, not user identity. Default CORS is `*` (`chat.py:37`). | Public mutation routes can be callable without authentication under defaults. Enforce deployment access policy and customer authorization; restrict CORS. Keep service keys server-side, never in `NEXT_PUBLIC_*`. The configured frontend cannot satisfy a service-key-only deployment today. |
| S5 — **High if enabled** | `ENABLE_DEBUG_RESPONSE=true` includes raw input, CRM profile, memory and past history (`chat.py:162`). Synthetic handler probe confirms these fields can be returned; local default is false, deployed flag unknown. | Do not expose customer context/diagnostics to unprivileged clients. Disable or redact production debug responses and restrict diagnostics by role. No live/private debug response was fetched. |
| S6 — **Medium / local boundary** | Guest phone/messages/drafts/address/receipts are plaintext SessionStorage; cart is shared LocalStorage. Synthetic stores demonstrate the same guest cart in another tab. There is no retention TTL or server owner binding for these records. | Local convenience is not account isolation; same-origin scripts/device users can inspect/tamper with it. Establish customer-scoped server data and a defined retention/clear policy. Do not accept stored demo prices/receipts as real order/payment evidence. |

Positive controls observed: configured service key rejects missing/wrong keys;
client handles permission failures without inventing login success; account UI
does not collect credentials; diagnostic/CRM objects are not saved in the guest
snapshot; identity changes require consent before clearing prior guest purchase
state; text rendering escapes HTML; uploads have client limits and bounded server
reads; chat/order duplicate guards and manual retries are tested. These do not
compensate for missing server authorization. A full penetration/dependency audit
was outside this targeted verification.

**Customer-isolation conclusion:** the requested guarantee that another user's
identifiers cannot access customer-specific state **cannot be given**. Independent
tab receipt isolation passes, but actual backend handler/resolver code lacks the
necessary customer authentication/ownership boundary. Isolated probes deliberately
remove route decorators to test selected functions; the optional service guard
was checked separately. They do not constitute a full ASGI or deployed exploit.

## 5. Blocking issues and recommended fixes

| Priority | Blocker | Required evidence before sign-off |
| --- | --- | --- |
| P0 | Customer authentication and session lifecycle absent (S1) | Verified test-account registration/login/logout/expiry/profile flows using approved real endpoints; no frontend-only authentication. |
| P0 | Conversation/customer identity not owner-bound (S2–S3) | Real HTTP negative tests for foreign conversation/customer/order IDs; unauthorized reads/mutations rejected before CRM, memory or order tools run. |
| P0 | Live backend cannot be exercised here | Provision an isolated configured test backend, Python dependencies, test DB/catalog and provider/ASR prerequisites. Health plus synthetic text/audio processing and error recovery must pass without mocks. |
| P0 | Cart/quote/order/payment/history remain local/demo | Approved authenticated public commerce contracts, server-calculated prices/fees/stock, transactional idempotent order submission and owner-scoped retrieval. Verify payment/status with test-provider evidence, not selected radio buttons. |
| P1 | Unsafe deployment defaults / debug exposure | Confirm explicit access policy/CORS and production debug redaction; verify no secrets enter client assets and no cross-customer context is returned. |
| P1 | Server history restore and streaming unsupported | Agree M3 scope explicitly. If required, provide and test those contracts; local snapshots/typing indicators must not be relabeled as server restore/streaming. |
| P1 | PDP policy sections and design documentation differ | Reconcile verified policy content and the approved PDF/Figma delta; obtain authorization for design synchronization. Keep unavailable photos and unverified promotions honest. |
| P2 | Local storage retention, optional visual feedback | Define guest retention/clear behavior; keep staff workspace, hero and decorative work deferred until essential M3 gates pass. |

Backend/data changes are recommendations only: their directories were read-only
for this task. No unavailable endpoint was invented or exposed through a proxy,
and no local demo was substituted for a real operation in the verification.

## 6. Final M3 verdict

**FAIL. Do not start M4 based on this verification.**

Frontend guest/demo behavior, SKU consistency and most high-impact feedback pass
their tests. M3 completion requires verified essential backend integrations and
no critical blockers. Missing customer auth/commerce, unverified live chat/ASR,
and reproduced ownership/identity weaknesses fail that gate. The build's sandbox
restriction is resolved for verification through a clean approved build and is
not the reason for the M3 failure. No M4 implementation was undertaken.
