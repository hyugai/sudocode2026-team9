# BTC category synchronization

Subsequent card cleanup adds read-only SKU PDP routes and removes catalog AI
buttons. See [PRODUCT-CARD-CLEANUP.md](./PRODUCT-CARD-CLEANUP.md) for the current
card/navigation behavior; the category mappings below remain unchanged.

Figma: https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=183-2183
Expanded review specimen: https://www.figma.com/design/MwKFun3Sk6RySDXDgovWx6?node-id=184-11997

## Design changes

The shared `SM / BTC Category navigation` component has All, Appliances, Air,
Water and Fryer selection states. It reuses SM / Category, its hover behavior,
existing tokens and type styles. Five equal-width top-level categories replace
seven: Tất cả, Điện gia dụng, Thời trang, Mẹ & bé, Phụ kiện. The appliance state
shows four 46px controls: all appliances plus the three requested subcategories.
A new shared appliance icon follows the existing SVG stroke conventions.

Two Homepage rows and three Prototype rows reference the shared navigation.
Appliance PDP breadcrumbs in the component library, Homepage, Prototype and
inherited Developer Handoff specimens include Điện gia dụng exactly once.
Purchase, chat, product-card links and other prototype flows were not edited.

## Data mappings

The adapter imports the original JSON without writing to it. Every one of the
40 base SKUs appears once, with its original name, list price and category path.
Variants remain in the original records and inherit their base product hierarchy;
this change does not add a variant selector or new purchase flow.

All three rows below have the top-level display category **Điện gia dụng**.

| Subcategory | Original BTC category | Base SKUs |
| --- | --- | --- |
| Máy lọc không khí | `gia-dung/may-loc-khong-khi` | `SKU-AP-X`, `SKU-AP-Y`, `SKU-AP-MINI`, `SKU-AP-PRO`, `SKU-XM-4L`, `SKU-XM-4P`, `SKU-SS-AX40`, `SKU-AP-X-2024` |
| Máy lọc nước | `gia-dung/may-loc-nuoc` | `SKU-WF-RO9`, `SKU-WF-RO10`, `SKU-WF-UF` |
| Nồi chiên | `gia-dung/noi-chien` | `SKU-AF-4L`, `SKU-AF-6L`, `SKU-AF-XM` |

The appliance parent contains 18 products: the 14 above, three fans and
SKU-BDL-AIR. Fans and the bundle appear under “Tất cả điện gia dụng”; their
source paths are not renamed and no extra subcategory is invented.
`gia-dung/phu-kien` and `thoi-trang/phu-kien` map to the existing Phụ kiện
navigation choice. Other fashion products map to Thời trang; `me-be` maps to
Mẹ & bé. All 40 records are covered, including zero-stock and legacy SKUs.
This is a reference catalog, not live availability or pricing.

Search matches name or SKU and intersects the chosen parent/subcategory.
Changing the parent resets the subcategory; clearing filters restores all SKUs.
The card markup and Ask AI action are reused. BTC contains no photos, ratings,
sales counts or publication dates. Cards and product details now use local,
SKU-mapped demo illustrations labelled “Ảnh minh họa”, with a text fallback
for unknown SKUs or image failures. Existing Bán chạy/Mới nhất controls remain visible and
explain why they are unavailable rather than inventing rankings.

Turbopack's root is the repository root so it can read the catalog outside web/.
Build from a full repository checkout; no generated catalog copy is maintained.
No backend or API contracts changed. No dependencies were added.

## Modified files

- `utils/catalog.ts`: read-only BTC adapter, display hierarchy and filtering.
- `app/components/storefront.tsx`: existing navigation/card integration.
- `app/globals.css`: balanced categories, subcategory controls, photo fallback.
- `next.config.ts`: repository root for external catalog resolution.
- `public/figma/category-appliance.svg`, `category-bag.svg`, `category-shirt.svg`:
  assets downloaded from the updated Figma design context.
- `tests/catalog.test.mjs`, `tests/category-browser.mjs`: mapping and UI checks.
- `tests/browser-check.mjs`: BTC expectations, localhost and lazy-image waiting.
- `CATEGORY-SYNC.md`: mappings, changes and validation evidence.
- `AGENTS.md`: automatic Next.js heading refresh, no policy changes.

## Verification

- `npm test`: both test files pass, including exact SKU membership, source field
  preservation, parent totals, search intersection and reset behavior.
- `npm run lint`: passed.
- `npx tsc --noEmit`: passed.
- `npm run build`: attempted; Turbopack's CSS worker fails with a local port
  permission error, including an approved retry outside the sandbox.
- `npm run build -- --webpack`: passed, including static generation and types.
- `node tests/category-browser.mjs`: 14 checks pass, covering desktop geometry,
  SVG loading, all requested SKU sets, search, clear/reset, 320px overflow,
  keyboard activation and the existing cart-unavailable dialog.
- `node tests/browser-check.mjs`: all 33 checks pass, covering text/audio API
  bodies, conversation/phone continuity, pending locks, audio preview/removal,
  manual retry, 429 cooldown, backend readiness, long replies, debug logs,
  floating chat, keyboard navigation and short/mobile viewports. Backend fetches
  are mocked; no live LLM, ASR or purchase requests were sent.
- `git diff --check`: passed. Next.js also refreshed its generated AGENTS heading.

Before/after screenshots and browser reports are in `/tmp/synee-categories/`;
the existing suite's screenshots and report are in `/tmp/synee-migration/`.
The category component was compared against the expanded Figma review specimen:
five 240px items at desktop, 104px row, 48px icon containers, 12px section gap,
8px chip gap, 46px chips, shared Inter styling and colors. At 320px the navigation
scrolls inside its container and remains keyboard accessible.

## Remaining verification limits

The standalone expanded Figma specimen renders all labels and chips correctly.
MCP reports the page instances at 1200×104 with all five labels, but page-instance
PNG exports stay at an old 1200×68 size and clip labels; even swapping the
instance to the expanded variant does not update those exports. Page-level visual
parity and interactive Figma playback therefore remain unverified. Initial All
state was restored after diagnostics. No claim of full Figma page parity is made.

The existing frontend has no PDP route or connected cart/checkout service.
Their unavailable behavior is preserved; an end-to-end purchase cannot be tested.
The Figma purchase prototypes are separate from those frontend capabilities.
