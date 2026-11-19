# KnowledgeFlow AI

[![CI](https://github.com/Shah-Vansh/knowledgeflow-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Shah-Vansh/knowledgeflow-ai/actions/workflows/ci.yml)

Enterprise Knowledge & Research Copilot — an AI knowledge platform built phase by phase to learn Retrieval-Augmented Generation (RAG) from the basics up to a production-shaped system.

## Current Status: all 17 phases (0–16) complete ✅

Documents (PDF, TXT, scanned pages, images) are ingested into workspaces, chunked, embedded locally and stored in PostgreSQL with pgvector and PostgreSQL full-text search. Questions are answered from those documents only, through hybrid retrieval, a local cross-encoder reranker, optional query transformation, conversation memory, a knowledge graph and a small LangGraph agent. Retrieval quality is measured with a golden-set evaluation and compared across configurations in an experimentation lab. The API has user accounts, per-workspace roles, token revocation, rate limits and prompt-injection hardening, rejects duplicate uploads, and can run uploads through a PostgreSQL job queue with a separate worker, structured logs, readiness checks and Prometheus metrics. The web app is a single-page workspace with a sidebar, a global workspace switcher and a consistent design system.

## Tech Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS
- **Backend:** Python 3.11, FastAPI, Pydantic, SQLAlchemy, Alembic, LangGraph
- **Database:** PostgreSQL 18 + pgvector (compiled from source) + built-in full-text search
- **Embeddings:** local `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim), no API key
- **Reranker:** local cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
- **OCR:** RapidOCR (ONNX), local
- **LLM:** Groq (`openai/gpt-oss-20b`), free tier
- **Auth:** Argon2id password hashing (`argon2-cffi`), HS256 JWT access tokens (`PyJWT`)

> **Note:** This project runs natively on Windows (no Docker). Docker Desktop needs WSL2/virtualization, which this machine's Windows image doesn't support. pgvector was compiled from source with Visual Studio Build Tools since no prebuilt Windows binary exists.

## Setup

### 1. PostgreSQL + pgvector

- Install PostgreSQL 16+ locally: https://www.postgresql.org/download/windows/
- Compile and install pgvector from source (requires Visual Studio Build Tools with C++ support):
```
  call "<path to>\VC\Auxiliary\Build\vcvars64.bat"
  set "PGROOT=C:\Program Files\PostgreSQL\<version>"
  git clone https://github.com/pgvector/pgvector.git
  cd pgvector
  nmake /F Makefile.win
  nmake /F Makefile.win install
```
  Use the latest pgvector release, not an old tag — older versions do not compile against PostgreSQL 18.
- Create the project database and enable the extension:
```sql
  CREATE DATABASE knowledgeflow;
  \c knowledgeflow
  CREATE EXTENSION IF NOT EXISTS vector;
```
  The test suite creates and migrates its own `knowledgeflow_test` database automatically; the database user needs permission to create databases (or create it yourself and enable `vector` in it).

### 2. Settings (one `.env` for the whole project)

All settings live in a single `.env` file at the repository root, shared by the backend and the frontend. From the repository root:

```
copy .env.example .env
```

`.env.example` lists every setting with comments; the important ones:

```
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/knowledgeflow
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:3000
GROQ_API_KEY=                # your Groq key; never commit .env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

The backend reads every key. The frontend reads only the `NEXT_PUBLIC_*` keys (they are built into the browser bundle, so never put a secret in one), so backend secrets in the same file never reach the browser. A variable set in the real environment overrides the file.

### 3. Backend

```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Apply database migrations and start the API:
```
alembic upgrade head
uvicorn app.main:app --reload
```
The API runs at http://localhost:8000 and the frontend at http://localhost:3000. Local models download once and load lazily, so the first request after a restart is slow.

### 4. Frontend

```
cd frontend
npm install
npm run dev
```
The frontend runs at http://localhost:3000. It takes `NEXT_PUBLIC_API_URL` from the root `.env`; restart `npm run dev` after changing it.

### 5. Verify

```
curl http://localhost:8000/health/ready
```
Expected: `{"status": "ready", "checks": {"database": true, "migrations": true}}`. A 503 with `"migrations": false` means `alembic upgrade head` hasn't been run.

## Turning on authentication

Auth is **off** by default so a single-user local install keeps working. To turn it on, set in the root `.env`:

```
AUTH_REQUIRED=true
JWT_SECRET=             # paste the output of the command below
```
Generate the secret (it is printed only in your own terminal; keep it out of git):
```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Restart the API, open http://localhost:3000/login and register. **The first account becomes owner of every existing workspace.** Later accounts need `REGISTRATION_OPEN=true` (the default) and start with no workspaces until an owner adds them on the workspace's members list. Set `REGISTRATION_OPEN=false` once your users exist.

**Sign out everywhere** (in the sidebar, or `POST /auth/logout-all`) revokes every token issued to your account: each token carries a version number that must match the user's current one.

With `ENVIRONMENT=production` the API refuses to start unless auth is on, the secret is long and random, the JWT algorithm is HS256/384/512, CORS lists explicit origins, and every route has an access policy. `/docs` is disabled in production.

## Running uploads in the background

By default an upload is processed inside the request (simple, but a scanned PDF can take a minute). For production:

```
INGEST_ASYNC=true
```
Uploads then return `202` at once with a `job_id`; the upload page polls `GET /jobs/{job_id}` and shows progress. Run one or more workers next to the API:
```
cd backend
venv\Scripts\activate
python -m app.worker
```
or set `RUN_EMBEDDED_WORKER=true` to run one worker thread inside the API process. Ctrl+C lets the current job finish first.

## Duplicate uploads

Each upload is fingerprinted (SHA-256 of the file bytes). Uploading a file that is already in the workspace returns `409` with the existing document's name and id; the same file may still go into another workspace, and a deleted or failed copy doesn't block a re-upload. Documents uploaded before this existed have no fingerprint; find and remove their duplicates (same workspace, identical extracted text, the oldest copy is kept) with:
```
backendenv\Scripts\python scriptsind_duplicates.py           # dry run
backendenv\Scripts\python scriptsind_duplicates.py --apply   # remove the extra copies
```

## Observability

- **Logs:** `LOG_FORMAT=json` writes one JSON object per line (time, level, logger, message, request id, and for the access log: method, route template, status, duration, user id). Bearer tokens, JWTs, passwords in URLs or `key=value` pairs and provider API keys are redacted in both text and JSON logs.
- **Request ids:** every response carries `X-Request-ID` (a well-formed incoming id is echoed), and every log line of that request carries the same id.
- **Health:** `GET /health/live` (process answers, never touches the database), `GET /health/ready` (database reachable and schema at the migration head; 503 otherwise), `GET /health` (original check).
- **Metrics:** `GET /metrics` in Prometheus text format: request counts and latency histograms by route template, job outcomes and durations, queue depth by status, oldest queued job age, and query-embedding cache hits/misses/size. Set `METRICS_TOKEN` (24+ characters) and scrape with `Authorization: Bearer <token>`; with auth on and no token, `/metrics` is disabled.

## Tests

```
cd backend
venv\Scriptsctivate
pytest                      # 548 backend tests

cd frontend
npm test                    # 31 frontend unit tests (Vitest)
npm run typecheck
npm run e2e                 # 14 browser tests (Playwright) against a running stack
```

Backend tests run against `<your database>_test` (created and migrated automatically; `KF_TEST_DB_RECREATE=1` rebuilds it) and refuse to run against a database whose name doesn't end in `_test`. All LLM-dependent tests use fake LLMs except one (`test_rag_pipeline_api.py`), which calls Groq only when `GROQ_API_KEY` is exported in the shell and skips otherwise. Embeddings and the reranker are the real local models.

The browser tests (`frontend/e2e/`, see its README) sign in, upload, refuse a duplicate, delete, inspect, retrieve, create and switch workspaces, manage members, visit every page through the sidebar without a reload, check for console errors and exercise the theme switch. Each test registers its own user and workspace. The chat test calls the LLM and runs only with `E2E_LLM=1`.

**CI:** every push to `main` runs three jobs on GitHub Actions (`.github/workflows/ci.yml`): the backend suite against a PostgreSQL + pgvector service container; the frontend unit tests, type check and production build; and the browser tests against the full stack (API with sign-in on, queued uploads and an embedded worker, plus the production frontend).

`python scripts/scan_secrets.py --history` checks tracked files and the whole git history for committed keys and passwords (it prints only file, line and kind, never the value).

## Features by Phase

| Phase | Feature | Status |
|---|---|---|
| 0 | Foundation — FastAPI + Next.js + PostgreSQL, health check | ✅ |
| 1 | Basic RAG — upload, chunk, embed, retrieve, grounded answer | ✅ |
| 2 | Chunking Laboratory — fixed-size, recursive, sentence strategies with overlap, side-by-side comparison | ✅ |
| 3 | Document & Metadata Management — page-level source attribution, soft delete, document-scoped queries | ✅ |
| 4 | Retrieval Laboratory — ranked retrieval debugging, configurable k/threshold | ✅ |
| 5 | Hybrid Search — dense (pgvector) + PostgreSQL full-text search fused with Reciprocal Rank Fusion | ✅ |
| 6 | Reranking — local cross-encoder over a 20-candidate pool, before/after ranks | ✅ |
| 7 | Query Transformation — rewrite, keyword expansion, multi-query, HyDE in one LLM call, fails open | ✅ |
| 8 | Conversational RAG — conversations with history; follow-up questions are rewritten into standalone questions before retrieval | ✅ |
| 9 | Workspaces — separate knowledge spaces; every query, conversation and document belongs to one | ✅ |
| 10 | Multimodal ingestion — tables kept as Markdown tables, OCR for scanned pages and images, text found in embedded images; an ingest report says what was read and what was skipped | ✅ |
| 11 | Agentic RAG — a LangGraph state machine; one LLM router call picks RAG, graph, document search, metadata or a safe calculator, falling back to RAG | ✅ |
| 12 | Graph RAG — LLM-extracted entities and relations, each verified against its source chunk; graph traversal fused with hybrid retrieval | ✅ |
| 13 | Evaluation — golden sets labelled by evidence text; hit@k, recall@k, precision@k, MRR, NDCG; optional LLM-judged faithfulness and correctness | ✅ |
| 14 | Experimentation Lab — compare retrieval and chunking variants on one eval set with paired bootstrap confidence | ✅ |
| 15 | Security — accounts, viewer/editor/owner roles per workspace, one deny-by-default policy table, rate limits, upload content checks, prompt fencing and answer sanitizing, security headers | ✅ |
| 16 | Production runtime — PostgreSQL job queue (`SKIP LOCKED`) with retrying workers, query-embedding cache, JSON logs with redaction, readiness checks, Prometheus metrics | ✅ |

## After the roadmap

Work done once all 17 phases were complete:

- **UI redesign** — one app shell with sidebar navigation (no page reloads), a global workspace switcher, a design system, a dashboard and a redesigned sign-in page
- **Workspace members** — add teammates by email, change their role (viewer, editor, owner) or remove them
- **Safer uploads and sessions** — duplicate uploads are rejected, "Sign out everywhere" revokes all of a user's tokens, and the last-owner check is locked against races
- **Readable answers** — Markdown in answers (bold, lists, code) is rendered safely, never as raw HTML
- **Dark mode** — Light / Dark / System, applied before the page paints so there is no flash
- **Testing and CI** — frontend unit tests (Vitest), browser tests (Playwright) and GitHub Actions running every suite on each push

## Application

One app shell: a sidebar with every page, the **active workspace** switcher (every page works inside it), backend status, the theme switch (Light / Dark / System) and the signed-in user. Moving between pages is client-side, so nothing reloads.

| Section | Page | What it does |
|---|---|---|
| | `/` Dashboard | Document and conversation counts, recent documents, quick actions |
| Ask | `/chat` | Conversations with follow-up questions and cited sources |
| | `/query` Quick answer | One-off questions, optionally limited to chosen documents |
| | `/agent` | The routed agent, showing which tool answered |
| | `/graph` Knowledge graph | Build and explore the graph, ask graph-augmented questions |
| Library | `/upload` | Drag-and-drop upload with background progress |
| | `/documents` | Documents in the workspace, delete |
| | `/inspector` | How each file was read: text, tables, OCR pages, text in images |
| | `/workspaces` | Create, switch and delete workspaces; manage members and roles |
| Labs | `/chunking-lab` | Compare two chunking setups on one document |
| | `/retrieval-lab` | Dense vs full-text vs hybrid, reranker, query transformations |
| | `/eval` Evaluation | Golden sets, runs, per-question results |
| | `/experiments` | Variants compared against a baseline with confidence intervals |
| | `/login` | Sign in / register (only when auth is on) |

## Architecture

```
Upload (PDF/TXT/PNG/JPG)
      ↓  size limit, extension AND content signature checked
[INGEST_ASYNC] document "queued" + job row (same commit) → 202 → worker claims job (SKIP LOCKED)
      ↓
Typed elements: text | table | ocr | image_text   (bounded OCR, every skip reported)
      ↓
Chunking (fixed_size | recursive | sentence; tables by rows with the header repeated)
      ↓
Embedding (local) → PostgreSQL: pgvector embedding + generated full-text search_vector
      ↓ (optional, per document)
Knowledge graph: LLM-proposed entities/relations, kept only if the cited chunk supports them

Question (+ conversation history → standalone question)
      ↓
[agent] one LLM router call → rag | graph | document search | metadata | calculator
      ↓
[optional] query transformation (one LLM call, fails open)
      ↓
Dense + PostgreSQL full-text search per query → Reciprocal Rank Fusion → 20 candidates
      ↓  (graph evidence chunks fused in for graph questions)
Cross-encoder rerank against the ORIGINAL question → top 5
      ↓
Grounding gate → prompt with every passage fenced as untrusted <document> data
      ↓
LLM (Groq) → answer sanitized (no images, active HTML or script URLs) + sources
```

Every request passes one access dependency driven by a single policy table (`app/core/access.py`): public, any signed-in user, or a minimum workspace role, with the workspace resolved from the path, query, body, form or the resource being touched. A route without a policy is denied, and the app refuses to start if one exists. A non-member gets exactly the same 404 as a missing item, so ids can't be probed.

`EmbeddingProvider`, `LLMProvider` and `Reranker` sit behind interfaces (`app/rag/embeddings.py`, `app/rag/llm.py`, `app/rag/reranker.py`); the project moved from OpenAI to local embeddings + Groq without touching any other file.

## Retrieval Strategies

- **Dense:** the query is embedded and compared to chunk embeddings by cosine distance. Strong on paraphrase and meaning, weaker on exact tokens such as IDs and numbers.
- **Sparse:** PostgreSQL full-text search (`tsvector` / `ts_rank`). Strong on exact terms, but requires every query term to appear in a chunk, so paraphrased queries can return nothing.
- **Hybrid:** both run over a candidate pool and are fused with Reciprocal Rank Fusion (`k=60`). Fusing by rank avoids comparing cosine distances with text-search scores, which are on incomparable scales.
- **Reranking:** a cross-encoder reads the question and each candidate together. More precise than embeddings but can't be precomputed, so it runs only over the 20-candidate pool, and can only reorder what retrieval found.
- **Query transformation:** one LLM call can produce a rewrite, expansion keywords (searched with OR), paraphrases and a hypothetical answer passage (HyDE). The original query is always searched too, and reranking and grounding use the original question.
- **Graph:** entities named in the question are linked to the graph, relationships are walked up to N hops, and the chunks those relationships came from are fused with the hybrid results.

## Known Limitations

**Retrieval and answers**
- The sparse retriever is PostgreSQL full-text search with `ts_rank`, **not** BM25 (no IDF weighting or length normalization). Plain sparse search requires all query terms to match.
- Rerank and RRF scores are relative, so neither is used as a relevance cutoff. The similarity threshold only decides whether to answer at all.
- Query transformation, conversation rewriting, the agent router and graph extraction each cost LLM calls; with Groq's free tier, calls are scarce.
- Duplicate detection compares exact file bytes: a re-saved or re-exported copy of the same document counts as a different file. Rechunking discards page numbers (stored text is flat).
- Images are searchable only through the text OCR finds in them; there are no image embeddings.
- With a small golden set most experiment differences are not statistically significant, and the LLM judge is the same model family as the generator, so faithfulness/correctness scores are indicative only.

**Security**
- Prompt fencing and answer sanitizing *reduce* prompt-injection risk; no prompt format can prove a model won't follow a cleverly written document.
- Login tokens are kept in browser localStorage, so an XSS bug in the frontend could read them (no cookies means no CSRF exposure). "Sign out everywhere" revokes all of a user's tokens at once; there is no per-device revocation.
- Rate limits are counted in memory per process and reset on restart; with several API processes each has its own budget.
- Workspaces created while auth is off, after users exist, have no owner until one is added in the database.
- Chunked uploads (no `Content-Length`) skip the early 413, but the upload handler still enforces `MAX_UPLOAD_MB`. UTF-16 `.txt` files are rejected (the text check refuses NUL bytes).

**Runtime**
- Queued uploads are stored in the `jobs` table until processed (then cleared), so very large queues use database space.
- A job whose worker dies stays "running" until `JOB_STALE_AFTER_SECONDS` (default 15 minutes) passes, then it is retried.
- Metrics and the embedding cache are per process; Prometheus sums several processes, but cache hits aren't shared between them.
- `/health/ready` checks the database and migrations, not that a worker is running; watch `kf_jobs_oldest_queued_seconds` for that.
- Local models load lazily, so the first request after a restart is slow.

## Project Structure

```
knowledgeflow-ai/
├── backend/
│   ├── app/
│   │   ├── main.py            # app, middleware, routers (all behind the access guard)
│   │   ├── worker.py          # `python -m app.worker`
│   │   ├── core/              # config, access policies, security, rate limits, HTTP hardening,
│   │   │                      # logging (JSON + redaction), metrics
│   │   ├── db/                # SQLAlchemy models, session
│   │   ├── jobs/              # PostgreSQL job queue and worker
│   │   ├── rag/               # parsers, multimodal, chunker, embeddings (+ cache), llm, retriever,
│   │   │                      # reranker, query_transform, conversation, graph, evaluation,
│   │   │                      # experiments, safety, pipeline
│   │   ├── agent/             # LangGraph workflow, router, tools
│   │   └── api/               # route handlers
│   ├── alembic/               # migrations 0001–0011
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/               # Next.js App Router pages
│       ├── components/        # AppShell (sidebar), AuthGate, ui.tsx design system, icons
│       └── lib/               # API clients
├── docs/                      # RESUME.md — project summary, resume bullets, interview notes
└── scripts/                   # scan_secrets.py, find_duplicates.py
```

## Git Checkpoints

Each verified phase is tagged: `phase-0-foundation`, `phase-2-chunking`, `phase-3-metadata`, `phase-4-retrieval-lab`, `phase-5-hybrid-search`, `phase-6-reranking`, `phase-7-query-transformation`, `phase-8-conversational-rag`, `phase-9-workspaces`, `phase-11-agentic-rag`, `phase-12-graph-rag`, `phase-15-security`, `phase-16-production`. Phases 1, 10, 13 and 14 were committed together with neighbouring phases and have no tag of their own.

## License

Personal learning project.
