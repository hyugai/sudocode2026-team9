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

Cart, login, live voice, order tracking and inventory services are not connected. Product data is the approved Figma demonstration catalog. Real text chat and audio uploads use the existing backend; messages are kept in memory for the current page session.
