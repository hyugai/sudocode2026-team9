# Repository Guidelines

## Project Structure & Module Organization

This project implements a Vietnamese telesales agent with text chat and local voice recognition.

- `src/telesale_agent/`: Python backend; `core/` defines domain contracts, `application/` orchestrates conversations, `adapters/` integrates services, and `entrypoints/api/` exposes FastAPI and Gradio interfaces.
- `src/mcp_servers/`: MCP servers and tools for catalog, CRM, orders, knowledge, and memory.
- `src/web/`: Next.js/React frontend; routes in `app/`, client logic in `utils/`, and assets in `public/`.
- `tests/` and `src/web/tests/`: regression tests. `src/eval/`, `evaluation/`, and `dataset/` support benchmarks.
- `scripts/`: setup and ingestion utilities. `docs/`: architecture and deployment guides.

## Build, Test, and Development Commands

Use Python 3.11+ in a virtual environment. From the repository root:

```bash
python -m pip install -e ".[dev,voice]"
python -m uvicorn telesale_agent.entrypoints.api.chat:app --app-dir src --reload
python -m unittest discover -s tests -v
```

These install dependencies, start the API, and run backend tests. Download optional voice weights with `python scripts/download_asr_model.py`.

From `src/web/`, run `npm install`, then:

- `npm run dev`: start the frontend.
- `npm run build`: create a production build.
- `npm test`: run Node's test runner; use Node 24 for TypeScript stripping support.
- `npm run lint` and `npx tsc --noEmit`: check ESLint rules and TypeScript types.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, `snake_case` functions/modules, `PascalCase` classes, and type hints for interfaces. Frontend code uses two-space indentation, semicolons, and camelCase identifiers. ESLint applies Next.js Core Web Vitals and TypeScript rules. Read `src/web/AGENTS.md` before frontend changes.

## UI/UX Guidelines

- Prioritize the core flow: identify the customer, enter text or upload audio, send, and read the response. Keep debugging details in the separate logs view.
- Follow the existing warm neutral surfaces, dark navigation, rounded controls, and restrained borders. Reuse spacing and typography; define shared design tokens in `src/web/app/globals.css` when styles repeat. Use Tailwind utilities and existing SVG conventions.
- Write concise Vietnamese labels, instructions, and actionable errors. Preserve diacritics and verify long messages, phone numbers, and transcripts wrap correctly.
- Design for mobile and desktop. Keep navigation, customer identification, and the composer usable at 320px width without horizontal page scrolling; account for the mobile keyboard.
- Use semantic controls, associated input labels, visible keyboard focus, accessible names for icon buttons, and comfortably sized touch targets. Announce processing and errors through appropriate live regions; never communicate status through color alone. Respect reduced-motion preferences.
- Show backend readiness, processing, upload limits, and rate-limit countdowns clearly. Explain disabled send controls, preserve input/audio on failure, and prevent duplicate submissions. Keep conversation IDs consistent between text and voice; retain manual retry behavior.

## UI/UX Validation

For frontend changes, run `npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build` from `src/web/`. Check mobile/desktop layouts, keyboard navigation, long conversations, audio preview/removal, unavailable backend, and error recovery. Include before/after screenshots in UI PRs and state any checks you could not perform.

## Testing Guidelines

Backend regressions use `unittest`; pytest and pytest-asyncio are also declared dependencies. Name tests `test_*.py` or `*.test.mjs`. Mock external services; cover normalization, API errors, and conversation sequencing. Real ASR tests may skip without downloaded weights. No coverage threshold is configured. Ignore rules match test directories; verify new tests are tracked.

## Commit & Pull Request Guidelines

Recent commits use `feat:` and `fix:` prefixes. Write concise, action-oriented subjects. PRs should describe behavior changes, link relevant issues, report validation results, and include screenshots for UI changes.

## Security & Configuration

Configure `.env` from `.env.example`; keep credentials out of Git. Set `NEXT_PUBLIC_API_BASE_URL` in `src/web/.env.local` when needed. Keep downloaded weights in ignored `models/` and review customer-memory changes before committing.
