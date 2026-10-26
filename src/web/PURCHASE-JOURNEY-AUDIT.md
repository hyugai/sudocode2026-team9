# Purchase journey audit

Subsequent account, guest-session restoration, PDP chat and purchase-clarity
changes are documented in [FEEDBACK-UI-AUDIT.md](FEEDBACK-UI-AUDIT.md).

## Baseline before implementation

Figma is read-only for this task. Inspected through MCP: PDP 143:334/143:419;
Cart 145:304; Checkout 145:365/145:722; Review 145:450; Success 145:514;
Order details 145:577; Tracking 145:641; purchase variant/state inventory on
17:3 and prototype/state inventory on 17:5.

| Figma requirement | Code before | Completion target |
| --- | --- | --- |
| 40 exact SKU card-to-PDP routes | Present; previously browser-tested | Retain and recheck |
| Gallery/specs/variant/stock/quantity | Placeholder gallery and specs; variants read-only; no stock or quantity controls | Select actual variants, snapshot stock, valid quantities; honest missing photos |
| Add to cart / buy now | Missing | Distinct cart and direct-checkout intents |
| Cart | Unavailable dialog | Persistent multi-line cart, edit/remove/count/totals |
| Checkout | Missing | Address fields, delivery region, COD and online demo methods |
| Review | Missing | Exact lines/totals plus explicit confirmation, duplicate guard |
| Success/details/tracking | Missing | Persisted, distinctly DEMO-prefixed receipts; no fabricated carrier activity |
| Empty/loading/invalid/failure | Only chat states | Commerce loading, empty, unavailable, validation and manual retry |
| Chat continuity | Provider preserves messages/ID/draft/audio; Voice mode local; PDP action overwrites drafts | Shared mode; separate visible SKU context, user-initiated text send |

Desktop purchase screens use the existing 1200px container, 800/368 columns,
32px gap, 24px vertical rhythm, white 16px-radius panels, Inter 28/36 headings,
and signature SUDO CODE conversion controls. Mobile stacks the same sections.
The prototype's one-line/two-unit limit is a specimen, not a production cart.

## API boundary

`src/telesale_agent/entrypoints/api/chat.py` exposes health, JSON chat,
multipart audio and session deletion. There is no HTTP cart, quote, stock,
checkout, payment, order-creation or order-status endpoint. Order/catalog tools
are internal FastMCP stdio tools (`src/mcp_servers/mcp_db.py`), backed by the
existing database; no browser contract/authentication gateway exists for them.
The task forbids backend-contract changes. Chat remains integrated through its
existing contracts. Commerce therefore uses an explicitly labeled local demo
adapter; it never submits a hidden chat turn to create orders.

BTC reference: 2026-10-15. Read-only products.json and inventory_timeline.json
supply SKU/variants/list prices and dated stock. Shipping is based on
policy/chinh-sach-van-chuyen-thanh-toan.md VC-01–04. No customer-dependent
promotion is assumed, and no live quote, reservation, payment or delivery date
is represented as verified.

## After implementation

| Area | Before | After / verified limit |
| --- | --- | --- |
| Card → PDP | 40 routes present | All 40 still return their exact SKU; card semantics and dimensions retained |
| Gallery/specifications | Missing-image state and specs | Existing gallery layout, honest missing-image/thumbnail state and BTC specs retained; actual photos are still absent upstream |
| Variant/quantity/availability | Read-only variant list; no quantity or inventory | Exact size/color selection, variant SKU and price delta, integer quantity bounds, discontinued/out-of-stock states; inventory timeline overrides static counts at the declared snapshot date |
| PDP actions | AI only, draft overwritten | Add to cart; isolated buy-now checkout; selected SKU/price/quantity consultation separate from nonempty draft |
| Cart | Unavailable dialog | Multiple SKU lines; add/merge/update/remove; stock bounds; totals/count; reload persistence; empty/invalid/storage-failure states |
| Checkout | Missing | Recipient/phone/address, delivery-region radios, COD/bank/MoMo/ZaloPay demo selection, policy shipping, actionable field validation |
| Review/confirmation | Missing | Immutable reviewed totals and exact lines; checkbox plus explicit action; stale-review detection; synchronous UI and store submission locks |
| Success/details/tracking | Missing | Persisted DEMO-prefixed receipt; exact saved SKU/quantity/prices/address; unpaid payment status; future carrier stages explicitly not occurred |
| Error recovery | Chat only | Manual order/payment failure and last-moment unavailability demos; storage errors preserve cart/form; no automatic order retry |
| Synee continuity | Shared conversation, local Voice toggle | Conversation ID/history/draft/audio and Chat/Voice persist across all purchase routes; no checkout address/phone writes to customer memory |

### Routes

- `/products/[sku]` — all 40 BTC product routes retained.
- `/cart` — persistent browser cart.
- `/checkout` — cart or isolated buy-now checkout.
- `/checkout/review` — explicit confirmation step.
- `/order-success/[id]` — saved local demo receipt.
- `/orders` — demo orders stored in the current tab.
- `/orders/[id]` — receipt details.
- `/orders/[id]/tracking` — distinctly simulated progress, no carrier claims.

### Files changed for this task

- `utils/commerce.ts`: pure snapshot selection/stock/shipping/validation functions;
  storage-backed demo adapter and idempotent receipt state machine.
- `utils/use-conversation.ts`: shared Voice mode and visible consultation context;
  context is included only on an explicit text send through the existing API.
- `app/components/purchase-provider.tsx`, `purchase-controls.tsx`,
  `purchase-journey.tsx`: one shared state owner, controls, order lines, price
  summary and purchase-screen implementation.
- `app/components/product-detail.tsx`, `storefront.tsx`, `chat-panel.tsx`: wire
  purchase actions/header/routes/context while reusing branding and chat UI.
- `app/layout.tsx`: persistent purchase provider beside the conversation owner.
- `app/globals.css`: scoped commerce layout/tokens, semantic form controls,
  focus feedback and mobile stacking.
- Seven new route files under `app/cart`, `app/checkout`, `app/order-success`,
  and `app/orders`.
- `tsconfig.json`: allow explicit `.ts` imports with noEmit, so the pure domain
  functions also run directly in Node 24 tests.
- `tests/commerce.test.mjs`, `tests/purchase-browser.mjs`: domain and E2E purchase
  coverage; existing browser suites updated for the newly implemented cart and
  non-overwriting consultation behavior.
- `tests/browser-support.mjs`: each suite uses and closes an isolated page so
  injected backend mocks cannot leak into later suites.

No dependency was added. Existing uncommitted category/card work was retained.
Figma, backend files and source datasets were not edited.

## Real integration vs demo behavior

| Operation | Implementation |
| --- | --- |
| Chat readiness, text, audio | Existing real HTTP client/contracts unchanged. Browser tests mock responses; no live LLM/ASR transaction was sent. |
| Product identity/variant/list price | Read-only BTC records; base price plus exact variant delta. |
| Stock | BTC dated snapshot, including inventory_timeline precedence; no live reservation or decrement. |
| Cart | LocalStorage stores only SKU identities and quantities. Invalid records are rejected or shown for removal; no stored price is trusted for totals. |
| Recipient/review/receipts | SessionStorage in the current tab; no CRM/customer-memory mutation. Closing/clearing the tab's session can remove demo orders. |
| Shipping | Deterministic VC-01/02 reference calculation; 25k inner/35k outside base fee, base freeship at 2M, active MOM-FREESHIP for qualifying mother-and-baby-only baskets, one 30k bulky surcharge outside inner areas; remote bulky shipping is blocked. Region is user-selected and address is not independently verified. |
| Discounts/gifts | Zero monetary discount; no automatic unverified customer-dependent discounts or gift claims. Mixed-category MOM-FREESHIP eligibility needs a live quote; the demo conservatively uses standard VC-02 fees there. |
| COD | Public VC-03 below-10M boundary enforced against total. Internal order tool uses >10M instead of >=10M; the UI uses the stricter published policy and documents the mismatch without changing the backend. |
| Online payment | Method selection and explicit failure scenarios only; no charge, transfer instructions, QR, card collection or false “paid” state. |
| Order creation | Local DEMO receipt only after review/confirmation; stable token replay prevents duplicate receipts, including refresh/retry. |
| Tracking | Only demo receipt acceptance is current. Preparation/shipping/delivery are explicitly “chưa diễn ra”; no fabricated carrier ID or ETA. |

The existing internal `order.create` tool supports one SKU per call. Turning a
multi-line web basket into live orders requires an authenticated, transactional
public commerce gateway with agreed quote/stock/idempotency semantics. Exposing
internal DB/MCP access through an unauthenticated invented endpoint would not be
an integration of the current browser contract, so this implementation does not
do that.

## Validation

- `npm test`: 21 domain/API tests across three files pass (10 commerce, four
  catalog, seven chat-client tests).
- `npm run lint`: passed.
- `npx tsc --noEmit`: passed.
- `npm run build -- --webpack`: passed with all purchase routes and 40 PDPs.
- `npm run build` (Turbopack), approved execution with isolated production
  cache: passed on the final application code.
- `tests/product-card-browser.mjs`: 19 checks pass, including successful exact
  responses for all 40 SKU routes, native keyboard navigation, mobile geometry,
  selected audio and conversation continuity.
- `tests/browser-check.mjs`: all 33 chat/audio/error/readiness/keyboard/mobile
  checks pass, including contextual PDP selection with no automatic send.
- `tests/category-browser.mjs`: all 14 filtering/navigation checks pass.
- `tests/purchase-browser.mjs`: 33 purchase checks pass. Representative paths
  cover exact variants, price/stock, multiple SKU totals, add/update/remove,
  persistence, address errors, COD limit, remote bulky shipping, fees, failed
  order/manual retry, repeated confirmations, successful COD and online demo
  receipts, unpaid status, details/tracking and unknown order state. An explicit
  text-send test checks the exact variant context and stable conversation ID.
  The populated 320px checkout fits without horizontal overflow; keyboard Tab
  follows recipient to phone and Space operates the explicit confirmation.
- `git diff --check`: passed. New tests are visible as nonignored files in Git
  status; no source datasets or backend files have a diff.

After screenshots and machine-readable reports are under `/tmp/synee-purchase/`,
`/tmp/synee-product-cards/`, `/tmp/synee-migration/` and `/tmp/synee-categories/`.
Purchase screenshots include full-page desktop cart/checkout/success/tracking and
320px cart/checkout/details/tracking, including the populated checkout form.
No pre-edit browser screenshots were
captured in this run; the source audit and MCP renders record the baseline.

### Visual/behavioral comparison limits

Reviewed the after screenshots against the inspected Figma layouts: same SUDO
CODE header/footer, 1200px container, 800/368 columns, 32px gap, white rounded
panels, Inter typography and signature conversion buttons. The working forms
add real input/radio/validation controls in place of prototype text fields.
Multi-line cards fill their column and include line totals. Delivery-region
coverage extends the two prototype choices to the regions in VC-01. These are
explicit functional adaptations; full pixel-for-pixel parity is not claimed.
No exhaustive native Figma prototype-playback test or live provider transaction
was performed. Gallery photography remains unavailable, rather than a completed
photo gallery being claimed from placeholders.

## Turbopack investigation (separate from application changes)

1. The restricted `npm run build` fails while PostCSS tries to bind a local
   worker port (`EPERM`), before reporting an application compilation error.
2. A minimal Node loopback-port probe also fails in the sandbox, but succeeds
   under approved execution. This isolates an environment restriction.
3. An approved build initially replays the same failure. The production
   Turbopack cache was moved intact to `/tmp/synee-turbopack-cache-purchase-audit`;
   a clean approved build then compiled/prerendered all routes successfully.
4. A deliberate restricted recheck failed again and cached the failure; that
   cache is preserved at `/tmp/synee-turbopack-cache-restricted-recheck`. A final
   clean approved Turbopack build passed. The running dev cache was not removed.

No CSS, Next.js version or app styling was changed to disguise the restriction.
A fresh restricted build still cannot open the required port. Use permitted
execution in this environment (and isolate an EPERM-poisoned production cache),
or the verified webpack build. No general Next.js regression is inferred from
this local sandbox behavior.

## Unresolved dependencies / next priorities

1. Define an authenticated public commerce gateway for real quotes, stock
   reservation, transactional multi-line orders and order status. Reuse existing
   MCP contracts behind it without exposing database credentials in the browser.
2. Resolve the exact-10M COD boundary and mixed-category promotion semantics
   with the backend/policy owner before accepting live orders.
3. Connect real payment and carrier providers with verified webhook/status and
   idempotency handling; retain review and duplicate-submission protections.
4. Supply actual BTC product photography; confirm live promotion eligibility,
   stock, address classification and delivery dates before real purchase claims.
