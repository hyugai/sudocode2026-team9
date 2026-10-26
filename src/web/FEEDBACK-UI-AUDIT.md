# Feedback UI implementation

Source: all eight pages of `Feedback UI.pdf`, including screenshots and yellow
annotations. Figma was inspected read-only through MCP: PDP 143:334 and purchase
screens 145:304, 145:365, 145:450 and 145:514 in file
`MwKFun3Sk6RySDXDgovWx6`. No Figma, backend or BTC changes are authorized.

## Priorities before editing

| PDF | Priority / impact | Cost | Decision |
| --- | --- | --- | --- |
| 1: login/register/logout/profile | Critical: identity and private-data access | High, backend dependent | No customer-auth endpoints exist. Show honest unavailable states; implement guest profile only. Never treat phone hints as authentication. |
| 1–2: account sidebar and history | Important: discoverability | Medium | Reuse dialog focus management as a drawer; link profile, orders, current-tab conversation history. |
| 2: redundant menu | Important: confusing navigation | Low | Keep categories in category menu; move account/history/orders to account menu. Keep header search/cart/account. |
| 3–5: grouping, PDP actions, shipping/payment | Important: selection errors and readability | Medium | Bordered white panels, clear selected options and aligned action hierarchy; preserve tokens and signature send button. |
| 5–6: review/back/success | Important: purchase confidence | Low | Explicit back action above review, clear success/status grouping, no continue-shopping links in checkout/review. |
| 6–7: contextual chat and view-all | Important: consultation/catalog access | Medium | Desktop PDP chat beside product; stacked mobile chat; working catalog anchors/filters. |
| 1: staff workspace | Optional in this pass | High | Defer: separate roles/contracts and scope. |
| 7: remove ordinary search | Optional, conflicts with user constraint | Low | Retain: direct SKU/text lookup complements AI. |
| 8: hero height/decorative buttons | Optional cosmetic | Medium | Defer broad changes; simplify secondary PDP action only. |

## API map before editing

Repository root: `/home/cookies/repos/sudocode2026-group_9`.
Backend: `src/telesale_agent/entrypoints/api/chat.py`.

| Contract | UI integration / limit |
| --- | --- |
| `GET /health`, `GET /` | Existing readiness; verify connectivity separately from mocked browser tests. |
| `POST /api/chat` | Existing JSON conversation_id/message/customer_phone contract; phone is an unverified hint. |
| `POST /api/chat/audio` | Existing multipart conversation_id/file/customer_phone contract. |
| `DELETE /api/sessions/{conversation_id}` | End current guest conversation only, after explicit confirmation; preserve local state on failure. |
| Optional `X-API-Key` service guard | No customer login, cookie, JWT, refresh or ownership contract. Never expose a service secret in frontend variables. |
| Auth/profile/history/cart/order/payment HTTP | Absent. No invented endpoints or simulated login. |
| `src/mcp_servers` CRM/catalog/order tools | Internal stdio/DB tools, not browser APIs; remain read-only. |

Cart and orders retain the existing explicitly labeled demo adapter. Product
identity/prices/variants come from BTC; inventory is the declared dated snapshot.
Local tab data is not authenticated customer data or proof of ownership.

## Implemented result

- The header account control opens a right-side native dialog drawer. Profile,
  demo orders and conversation history are grouped there. Native modal focus
  containment, Escape and labeled controls are retained. Dedicated routes:
  `/account` and `/account/conversations`.
- Login/register/logout are explicitly unavailable. No password form, fabricated
  customer session or new auth endpoint was introduced. The guest phone is only
  an opt-in consultation hint. Saving a different hint requires consent before
  removing prior conversation/draft and demo checkout/receipt data when present.
- Guest messages, UUID, draft, hint, Chat/Voice and selected-product context
  restore from bounded, validated SessionStorage in the same tab. Audio files
  stay in memory during navigation; they do not survive reload. Debug/CRM payloads
  are not persisted. Debug diagnostics remain in a collapsed history section.
- Ending a conversation requires confirmation and uses the existing DELETE
  contract. A matching `cleared` response is required before resetting local
  history. Unauthorized, unavailable and invalid responses preserve it; there
  is no automatic DELETE or POST retry.
- PDP chat uses the same shared ChatPanel in a desktop column beside the product,
  with a mobile stacked panel and height bounds for short viewports. Closing
  returns focus to Ask Synee. Drafts are retained; no message is auto-sent. The
  single upload icon, Chat/Voice toggle and signature send/retry layers remain.
- Product information and purchase actions have explicit surfaces and consistent
  alignment. Shipping/payment options have bordered blocks and visible selected
  states. Address, delivery and payment stay together on review and receipts.
- Review has a clear back action above the content. Checkout/review omit
  continue-shopping links. Order success groups the receipt, demo qualification
  and unpaid status. Price/fee source details are available in an expandable
  explanation instead of dominating the order actions.
- Category menu contains category links only. Orders/history moved to account;
  redundant header order navigation and placeholder Analytics were removed.
  Search/cart/account remain accessible. Both view-all links reset filters and
  navigate to actual catalog results; category links carry a validated category.

## Files

New: `app/account/page.tsx`, `app/account/conversations/page.tsx`,
`app/components/account-content.tsx`, `utils/conversation-session.ts`,
`tests/conversation-session.test.mjs`, `tests/feedback-browser.mjs` and this audit.
The source PDF was copied into `web/Feedback UI.pdf` as requested.

Updated: `README.md`, `PURCHASE-JOURNEY-AUDIT.md`, `app/page.tsx`, `app/globals.css`, `app/components/storefront.tsx`,
`info-dialog.tsx`, `chat-panel.tsx`, `product-detail.tsx`, `purchase-journey.tsx`,
`utils/use-conversation.ts`, `utils/chat-api.ts`, and existing chat, product-card
and purchase browser suites. No dependencies or backend contracts changed.

## Integration and remaining limits

The only new HTTP operation is the existing session DELETE. Health/text/audio
clients retain their contracts; 401/403 errors now explain unavailable permission
without suggesting a fake customer login. No service API key is placed in the
browser, and no authentication is bypassed. If the backend enables API_KEY, an
approved server-side deployment/authentication strategy is still required.

Read-only health probes to `localhost:8000/health` and the legacy configured
Render deployment did not receive an HTTP response in this environment. Local
connection failed and the deployed request timed out. Consequently live text,
ASR and session-deletion transactions were not verified; browser tests use
explicit mocks. No live provider transaction or customer-memory write was sent.

Authenticated profile access, user logout/expiration, cross-device history and
server-authorized order ownership cannot be implemented or verified without
customer-auth and ownership endpoints. Independent guest tabs do not have access
to each other's SessionStorage demo receipts. Browser storage is not an access
control boundary against someone using the same tab/device or editing storage;
phone numbers never grant order access.

Public cart/quote/stock/order/payment APIs remain absent. The previous purchase
adapter stays explicitly demo-only, with real BTC identities and dated reference
values. It does not create real orders, reserve stock, claim paid status or emit
carrier events. Missing BTC photography remains an honest missing-image state.

Figma remained read-only. These changes retain the inspected branding, token
palette, type, header, catalog cards and shared controls. Side-panel composition,
bordered selections and clearer action grouping implement the feedback; no claim
of pixel-for-pixel parity with the unmodified older prototype is made.

## Deferred

- Full staff/sales workspace: separate role/auth/data requirements and high cost.
- Hero-height and decorative refinements: optional, outside essential usability.
- Removing traditional search: declined because direct SKU lookup complements
  consultation and the task explicitly requires retaining it.
- Full signature-button redesign: deferred; send/retry and key conversion retain
  the approved layered style, while the secondary Ask Synee action is simpler.
- Live auth/commerce/ownership: blocked by absent public contracts, not silently
  replaced by browser mocks or local authentication.

## Verification

| Check | Result |
| --- | --- |
| `npm test` | Passed four test files. Each file was also executed directly with Node 24 TypeScript stripping: 26 named cases passed (4 catalog, 7 chat API, 10 commerce, 5 guest-session/API-deletion). |
| `npm run lint` | Passed without warnings. |
| `npx tsc --noEmit` | Passed. |
| `npm run build -- --webpack` | Passed on final code, including both account routes, purchase routes and 40 generated PDPs. |
| `node tests/feedback-browser.mjs` | 22 passed: sidebar, unavailable auth, profile, session restoration/identity changes, unique accessible IDs, 320px layout, desktop PDP chat, review/success grouping, guest-tab receipt isolation, unauthorized DELETE, confirmation and Escape focus return. |
| `node tests/browser-check.mjs` | 33 passed: homepage A/B/C, signature control geometry, long messages, short mobile viewport, audio preview/upload/removal, same conversation ID, backend failures/readiness/429 and diagnostics. |
| `node tests/product-card-browser.mjs` | 19 passed, including all 40 exact SKU routes, 404, native keyboard links, shared search and audio continuity. |
| `node tests/category-browser.mjs` | 14 passed: exact BTC SKU filter sets, responsive category navigation and keyboard selection. |
| `node tests/purchase-browser.mjs` | 33 passed: variants/stock/prices, cart persistence, shipping/payment constraints, multi-SKU demo checkout, failures/manual retry, duplicate submission guard and receipt/tracking. |
| `git diff --check` | Passed; backend and BTC paths have no diff. |

Total: 121 browser checks. Browser suites explicitly mock chat/service responses;
these are not evidence of a successful live backend transaction. Full customer
authentication, expired customer tokens and server-authorized order ownership
remain untestable because those contracts do not exist. Direct Node test runs
emit the existing nonfatal module-type inference warning; no package/module
configuration was changed merely to silence it.

The default Turbopack build was not rerun in this feedback pass. Its previously
documented sandbox worker-port restriction is separate from the passing webpack
production build; see the purchase audit for that investigation.

Before/after screenshots and the feedback report are in `/tmp/synee-feedback/`:
`before-pdp.png`, `before-account.png`, `after-pdp-chat.png`,
`after-pdp-chat-mobile.png`, `after-account.png`, `after-account-mobile.png`,
`after-checkout.png`, `after-review.png`, `after-success.png`, `results.json`.
Other suite reports remain in `/tmp/synee-purchase`, `/tmp/synee-product-cards`,
`/tmp/synee-categories` and `/tmp/synee-migration`. Screenshots were reviewed for
the requested layout/grouping changes, rather than claiming unchanged prototype
pixel parity.
