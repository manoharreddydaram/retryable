# Retryable — web

The Stage 9 UI: four read-only screens (Live Triage, Decision Detail, Audit
Ledger, Results) over the FastAPI read API in `src/api/`. See the root
[README.md](../README.md) for what this project is; this file only covers
running the frontend itself.

```bash
npm install
npm run dev
```

Runs on `:5173` and proxies `/api/*` to the FastAPI app on `:8000` (see
`vite.config.ts`) — start that with `make run` first. `make web` /
`.\tasks.ps1 web` run this from the repository root.

This UI only ever reads. Every write-capable action in this project goes
through `src/policy/engine.py` and `src/execute/outbox.py`, unchanged.
