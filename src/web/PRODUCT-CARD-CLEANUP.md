# Product-card cleanup

This records the earlier card cleanup. The subsequent implemented purchase
journey and its current validation are documented in
[PURCHASE-JOURNEY-AUDIT.md](./PURCHASE-JOURNEY-AUDIT.md).

## Figma

Shared component: [SM / Product card](https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=18-268).

The file already had CTA-free Default and Hover variants when inspected for this
request. Both retain 224 × 338 geometry, the 196px image placeholder, exact SKU,
name, price, rating availability, 16px information padding and 8px gaps. Their
content-driven Auto Layout was confirmed and the component description now
explicitly states that the whole card is the sole catalog action and that
“Hỏi Synee AI” belongs only on PDPs. No unnecessary component replacement was
made. The one obsolete Foundations text specimen (25:82) was changed to
“Xem chi tiết sản phẩm”.

Final audit across all five pages: zero obsolete “Hỏi AI về sản phẩm” strings.
All 20 Homepage card instances and 30 Prototype card instances have one full-card
click destination matching their own exact SKU. All remain 338px high. Their
existing navigation actions, product properties, hover behavior and the PDP's
“Hỏi Synee AI” action were preserved.

Modified Figma nodes: 18:268, 18:234, 18:236, 18:251, 18:253 and 25:82.
The existing 50 instance destinations required no edits.

## Code changed for this request

- `app/components/storefront.tsx`: replace each article/button with one Next.js
  Link covering the whole card; remove obsolete AI markup and handler; retain
  the shared header, footer, dialogs and chat presentation for the SKU PDP.
- `app/globals.css`: delete the obsolete button styles; use natural card height,
  preserve consistent name/price/metadata alignment, add visible link focus and
  scoped responsive detail-page styles from the existing Figma design.
- `app/products/[sku]/page.tsx`: real SKU detail route; prerender all 40 records
  and return 404 for unknown SKUs.
- `app/components/product-detail.tsx`: minimal read-only detail destination using
  the existing Figma gallery/information layout, original BTC fields and the
  PDP-only “Hỏi Synee AI” action. No cart/checkout flow was added.
- `app/components/conversation-provider.tsx` and `app/layout.tsx`: keep the existing
  conversation hook mounted during client navigation so drafts, history, phone,
  conversation IDs, pending requests and selected audio are not discarded.
- `app/page.tsx`: accept the shared header's catalog search after leaving a PDP.
- `utils/catalog.ts`: exact SKU lookup, detail type and encoded product URL helper.
- `tests/catalog.test.mjs`: all SKU lookups/URLs, unknown IDs and URL encoding.
- `tests/product-card-browser.mjs`: card and PDP regression checks.
- `tests/browser-check.mjs`: update obsolete card-action assertions to the new
  behavior while keeping the existing chat/audio/error tests.

BTC source records, backend APIs, dependencies and purchase-service contracts
were not changed. Existing unconnected cart/checkout behavior is preserved.
These read-only PDPs are not an implementation of the Figma purchase journey.

## Verification

- `npm test`: passed (catalog and chat API test files).
- `npm run lint`: passed.
- `npx tsc --noEmit`: passed.
- `npm run build`: attempted, including the required approved retry; Turbopack
  still fails to bind the CSS worker's local port in this environment.
- `npm run build -- --webpack`: passed; all 40 SKU PDPs prerendered.
- `node tests/product-card-browser.mjs`: 18 checks passed. All 40 exact SKU links
  and detail responses are checked; pointer clicks and native keyboard Enter
  navigate correctly; unknown SKU returns 404. Desktop cards are 224 × 338;
  mobile cards align without horizontal page overflow. Chat draft/history,
  phone, conversation ID and selected audio survive navigation. PDP AI never
  auto-submits and remains disabled while audio is selected. Shared-header
  search returns to the matching catalog result.
- `node tests/browser-check.mjs`: all 33 existing checks passed, including JSON
  and multipart contracts, UUID/phone continuity, manual retry, readiness,
  rate limits, audio preview/removal, escaping, keyboard focus and mobile chat.
- `git diff --check`: passed.

Browser API calls were mocked; no live LLM/ASR or purchase requests were sent.
Screenshots and the SKU-by-SKU report: `/tmp/synee-product-cards/`.
Existing chat-suite evidence: `/tmp/synee-migration/`.
The attempted new before capture failed because the duplicate dev server did
not start; after screenshots were visually reviewed against the inspected Figma
card and existing PDP design. No fabricated before screenshot is included.
