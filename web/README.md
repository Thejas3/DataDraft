# DataDraft web

Next.js 16 (App Router) front end for the DataDraft API. Built to `../DESIGN.md`.

```
npm install
DATADRAFT_API_URL=http://127.0.0.1:8000 npm run dev   # /api/* is proxied to datadraft serve
npm run typecheck && npm run lint
npm run e2e        # Playwright: seeded API (../tests/e2e_server.py) + next dev, desktop and phone
```

Routes: `/login`, `/court`, `/court/r/:slug`, `/waivers`, `/startsit`, `/players`,
`/players/:id`, and the public `/c/:slug` with `/c/:slug/card.png` (1080×1350) and its
1200×630 og:image. Card fonts are vendored TTFs in `assets/fonts` (SIL OFL).
