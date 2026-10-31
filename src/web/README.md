# SUDO CODE · Synee AI storefront

Next.js 16 / React 19 frontend migrated from Telesale Hub to the approved Synee AI Figma design. Existing text/audio API contracts are retained.

```sh
npm ci
# Optional: copy .env.example to .env.local and set your public backend URL.
npm run dev
```

The default backend is `http://localhost:8000` in development and the legacy Render URL in production. `NEXT_PUBLIC_API_BASE_URL` overrides it. Never put API keys in public environment variables. The backend must allow the frontend origin through CORS.

```sh
npm test
npm run lint
npx tsc --noEmit
npm run build
```

See [MIGRATION.md](MIGRATION.md) for the feature map, shared A/B/C behavior, browser regression instructions, screenshot locations, deployment limitations, and sandbox build fallback.

Product identity, list prices and variants come from the BTC catalog. Cart, checkout, receipts and tracking use an explicitly labeled local demo adapter; live inventory, orders and payments are not connected. Login, registration and customer authentication have no backend endpoints. The account sidebar and `/account` pages are guest consultation views.

Text chat and audio uploads retain the existing backend contracts. Conversation identity, messages, drafts and Chat/Voice restore within the same browser tab; selected audio stays in memory during navigation. Ending a conversation uses the existing session DELETE endpoint after confirmation. See [FEEDBACK-UI-AUDIT.md](FEEDBACK-UI-AUDIT.md) for the feedback checklist, API audit, validation and remaining service gaps, and [PURCHASE-JOURNEY-AUDIT.md](PURCHASE-JOURNEY-AUDIT.md) for commerce behavior.
