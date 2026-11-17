# Browser tests (Playwright)

These drive the real app in a browser against a running backend and frontend.

1. Start the backend with sign-in on, pointing at a **test** database:
   `AUTH_REQUIRED=true`, a `JWT_SECRET` (32+ random characters),
   `RATE_LIMIT_AUTH_PER_MINUTE=1000` (the tests register many users quickly), and optionally
   `INGEST_ASYNC=true RUN_EMBEDDED_WORKER=true` to cover the job queue.
2. Start the frontend with `NEXT_PUBLIC_API_URL` pointing at that backend.
3. Run:

```
cd frontend
set E2E_API=http://localhost:8000
set E2E_WEB=http://localhost:3000
set E2E_CHANNEL=msedge
npm run e2e
```

`E2E_CHANNEL=msedge` (or `chrome`) uses a browser that is already installed; leave it
empty after `npx playwright install chromium`. Each test registers its own user and
workspace, so the tests don't depend on each other or on existing data.
`chat.spec.ts` calls the LLM and only runs with `E2E_LLM=1`.
CI runs this suite on every push (`.github/workflows/ci.yml`).
