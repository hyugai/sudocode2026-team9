# SUDO CODE · Synee AI storefront

Next.js 16 / React 19 frontend migrated from Telesale Hub to the approved Synee AI Figma design. Existing text/audio API contracts are retained.

```sh
npm ci
# Optional: copy .env.example to .env.local and set your public backend URL.
npm run dev
```

The default backend is `http://localhost:8000` in development and `https://telesale-agent-api.onrender.com` in production. `NEXT_PUBLIC_API_BASE_URL` overrides it. Never put API keys in public environment variables. The backend must allow the frontend origin through CORS.

The storefront list and product detail pages now request `/api/catalog/products` and `/api/catalog/products/{sku}` from the backend. Those endpoints read products, variants and effective stock from PostgreSQL via `DATABASE_URL`. The web does not need a database credential. If the catalog API is unavailable, the list shows an error instead of substituting snapshot data.

The `data/*.json` files are retained only for the separate demo cart and checkout flow. After changing the source BTC catalog used by that demo, copy the three JSON files from `dataset/BTC-Data-Vong1-TEAMS/catalog/` into `src/web/data/` and run `node --experimental-strip-types --test tests/catalog.test.mjs` to check they match.

```sh
npm test
npm run lint
npx tsc --noEmit
npm run build
```

If Turbopack cannot start its CSS worker on Windows or in a restricted environment, use `npm run build -- --webpack` (or `npm run dev -- --webpack`).

The product list and detail pages use the PostgreSQL catalog, including variant prices and effective stock. Product detail purchase buttons are hidden until cart pricing is connected to the same catalog. Cart, checkout, receipts and tracking remain a separate local demo adapter; orders and payments are not connected. Login, registration and customer authentication have no backend endpoints. The account sidebar and `/account` pages are guest consultation views.

The storefront and product detail pages load product identity, prices, variants and stock from the backend's `/api/catalog/products` endpoints backed by PostgreSQL/Neon. If the catalog is unavailable, the UI shows an error instead of silently substituting demo products. The default production API is `https://telesale-agent-api.onrender.com`; set `NEXT_PUBLIC_API_BASE_URL` to override it for both catalog and chat/voice.

The separate cart, checkout, receipts and tracking routes still use an explicitly labeled local demo adapter and bundled BTC snapshots in `src/web/data`. Product detail pages do not submit live catalog items to this demo checkout. Live orders and payments are not connected. Login, registration and customer authentication have no backend endpoints. The account sidebar and `/account` pages are guest consultation views.

Text chat and audio uploads retain the existing backend contracts and share a conversation ID. Messages, drafts and the selected mode restore within the same browser tab; selected audio stays in memory during navigation. Ending a text conversation uses the existing session DELETE endpoint after confirmation.

The Voice button opens the existing realtime voice client in a shared dialog. It checks `/api/voice/capabilities` and starts microphone capture only after **Bắt đầu trò chuyện** is pressed. The dialog stays mounted across inline/floating chat changes and client navigation. Closing it, pressing Escape or ending the call releases the microphone, audio context, WebSocket and voice session. Voice uses its own backend session and preserves mute, interruption, resampling and buffered playback from this branch. See [Gemini Live setup](../../docs/deployment/gemini_live.md) for backend configuration.

The voice dialog uses the [LiveKit Agents UI Wave](https://docs.livekit.io/reference/components/agents-ui/component/agent-audio-visualizer-wave/) with `size="xl"`, `color="#00ff26"`, `colorShift={2}` and `lineWidth={6}`. It takes explicit `state` and `volume` from the existing voice client rather than `useAgent()`, which requires a LiveKit session. No room/token service is needed. Playback volume is measured from the rendered PCM samples at up to 20 Hz; buffered audio keeps the speaking state until playback finishes or is interrupted. Reduced motion and unavailable WebGL use a static wave. Upstream source and licenses are documented in [components/agents-ui/NOTICE.md](components/agents-ui/NOTICE.md).

Browser regressions in `tests/*browser.mjs` and `tests/browser-check.mjs` use a separate headless Chromium instance exposing `CDP_URL` (default `http://127.0.0.1:9222`). Set `BASE_URL` to the running frontend and `BROWSER_ARTIFACT_DIR` to an output folder. Run `node tests/voice-browser.mjs` for the realtime voice integration, Wave states and reduced-motion fallback with mocked microphone, audio and backend services.

For catalog integration checks without a database, start `node tests/catalog-fixture.mjs` (localhost port 8100), point the frontend's `NEXT_PUBLIC_API_BASE_URL` to `http://127.0.0.1:8100`, then run `node tests/live-catalog-browser.mjs`. This verifies API-backed prices, product consultation, catalog outages and the LiveKit dialog. The legacy purchase browser suites target the original demo product pages; live product pages deliberately do not expose demo purchase actions. Unit contract probes also require Python 3.11+; set `PYTHON` to a virtual environment's executable when needed.
