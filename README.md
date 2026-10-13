# KnowledgeFlow AI

Enterprise Knowledge & Research Copilot — an AI knowledge platform built progressively, phase by phase, to learn Retrieval-Augmented Generation (RAG) from beginner to production level.

## Current Status: Phase 7 — Query Transformation ✅

A working RAG pipeline with configurable chunking, page-level source attribution, document lifecycle management, hybrid retrieval (dense vector search + PostgreSQL full-text search fused with Reciprocal Rank Fusion), a local cross-encoder reranker, optional LLM query transformation (rewrite, keyword expansion, multi-query, HyDE), and dedicated chunking and retrieval debugging interfaces — built and verified through eight phases, each tested before moving to the next.

## Tech Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- **Database:** PostgreSQL + pgvector (compiled from source) + built-in full-text search
- **Embeddings:** Local, free — `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim), runs entirely on-device, no API key or cost
- **Reranker:** Local cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`), runs on-device
- **LLM:** Groq (`openai/gpt-oss-20b`), free tier

> **Note:** This project runs natively on Windows (no Docker). Docker was evaluated but dropped due to a Windows image on this machine that doesn't support WSL2/virtualization required by Docker Desktop. pgvector was compiled from source using Visual Studio Build Tools since no prebuilt Windows binary exists.

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

### 2. Backend

```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Copy the example env file and edit it:
```
copy .env.example .env
```

Fill in `backend/.env`:
```
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/knowledgeflow
ENVIRONMENT=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000

GROQ_API_KEY=gsk_your_key_here
GROQ_LLM_MODEL=openai/gpt-oss-20b
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIM=384
TOP_K=5
SIMILARITY_THRESHOLD=0.8

RERANK_ENABLED=true
RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANK_CANDIDATES=20

QUERY_TRANSFORMS=
MULTI_QUERY_COUNT=3
```

`QUERY_TRANSFORMS` is the default strategy list for `/query` (comma-separated from `rewrite`, `expand`, `multi_query`, `hyde`). Leave it empty to run without query transformation.

Apply database migrations:
```
alembic upgrade head
```

Run the backend:
```
uvicorn app.main:app --reload
```
Backend runs at http://localhost:8000. The embedding model (and, on first reranked request, the cross-encoder, ~90 MB) downloads once and loads lazily, so the first request after a restart is slow.

### 3. Frontend

Open a new terminal:
```
cd frontend
npm install
copy .env.example .env
```

`frontend/.env`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Run the frontend:
```
npm run dev
```
Frontend runs at http://localhost:3000

### 4. Verify everything is connected

```
curl http://localhost:8000/health
```
Expected: `{"status": "ok", "db_connected": true, "environment": "development"}`

Open http://localhost:3000 — you should see a green "Backend Connected" status.

## Run Backend Tests

```
cd backend
venv\Scripts\activate
pytest
```

One test (`test_rag_pipeline_api.py`) requires a `GROQ_API_KEY` exported as a shell environment variable to run (it calls the live LLM); it skips cleanly otherwise. The query-transformation tests use a fake LLM, so they make no API calls.

## Features by Phase

| Phase | Feature | Status |
|---|---|---|
| 0 | Foundation — FastAPI + Next.js + PostgreSQL, health check | ✅ |
| 1 | Basic RAG — upload, chunk, embed, retrieve, grounded answer | ✅ |
| 2 | Chunking Laboratory — configurable strategies (fixed-size, recursive, sentence), overlap, side-by-side comparison | ✅ |
| 3 | Document & Metadata Management — page-level source attribution, soft delete with cascade, document-scoped queries | ✅ |
| 4 | Retrieval Laboratory — raw ranked retrieval debugging, configurable k/threshold, live threshold recompute | ✅ |
| 5 | Hybrid Search — dense (pgvector) + sparse (PostgreSQL full-text search) fused with Reciprocal Rank Fusion; dense / sparse / hybrid comparison in the Retrieval Lab | ✅ |
| 6 | Reranking — local cross-encoder re-scores a 20-candidate pool; before/after rank view in the Retrieval Lab | ✅ |
| 7 | Query Transformation — rewrite, keyword expansion, multi-query, HyDE (one LLM call, fails open), multi-list RRF, per-chunk provenance | ✅ |
| 8–16 | Conversational RAG, Multi-Workspace, Multimodal RAG, Agentic RAG, Graph RAG, Evaluation, Experimentation Lab, Productionization, Security | 🔜 |

## Application Pages

- `/` — health check / connection status
- `/upload` — upload PDF/TXT documents with optional chunking configuration
- `/query` — ask questions, optionally scoped to specific documents, with page-level source attribution
- `/documents` — manage uploaded documents (view metadata, delete)
- `/chunking-lab` — compare chunking strategies side by side on the same document
- `/retrieval-lab` — compare dense, sparse, and hybrid retrieval on the same query; toggle the reranker and each query-transformation strategy; see the generated rewrite/keywords/variants/hypothetical passage, per-method scores, rank changes, and which query surfaced each chunk

## Architecture

```
Document Upload (PDF/TXT)
      ↓
Page-aware Text Extraction
      ↓
Chunking (fixed_size | recursive | sentence, configurable)
      ↓
Embedding (local, sentence-transformers)
      ↓
PostgreSQL: pgvector embedding + generated full-text search_vector (GIN index)

Question
      ↓
[optional] Query transformation — ONE LLM call returning JSON
      rewrite | expand (keywords) | multi_query | hyde
      (fails open: on any error, only the original query is searched)
      ↓
Search jobs: the original query (always) + one per transformation
      each runs dense (pgvector cosine) and/or sparse (PostgreSQL full-text)
      ↓
Reciprocal Rank Fusion across all result lists → candidate pool (20)
      ↓
[optional] Cross-encoder reranking, scored against the ORIGINAL question → top 5
      ↓
Grounding gate — judged on the ORIGINAL query's own signals only
      (dense within threshold OR a sparse keyword hit)
      ↓
Context Assembly → LLM (Groq) → Grounded Answer + Deduplicated Sources
```

`EmbeddingProvider`, `LLMProvider` and `Reranker` are abstracted behind interfaces (`app/rag/embeddings.py`, `app/rag/llm.py`, `app/rag/reranker.py`) — the project originally used OpenAI for both embeddings and generation and was swapped to local embeddings + Groq mid-build with zero changes to any other file.

## Retrieval Strategies

- **Dense:** the query is embedded and compared to chunk embeddings by cosine distance. Strong on paraphrase and meaning, weaker on exact tokens such as IDs and numbers.
- **Sparse:** PostgreSQL full-text search (`tsvector` / `ts_rank`). Strong on exact terms, but requires every query term to appear in a chunk, so paraphrased queries can return nothing.
- **Hybrid:** both run over a candidate pool and are fused with Reciprocal Rank Fusion (`k=60`). Fusing by rank position avoids comparing cosine distances with text-search scores, which are on incomparable scales. If one method returns nothing, hybrid falls back to the other.
- **Reranking:** a cross-encoder reads the question and each candidate chunk together and re-scores them. It is more precise than embeddings but cannot be precomputed, so it runs only over the 20-candidate pool. It can only reorder what retrieval already found.
- **Query transformation:** a single LLM call can produce a rewritten query, expansion keywords (searched with OR semantics), paraphrases, and a hypothetical answer passage (HyDE, embedded in place of the question). The original query is always searched too, and reranking and grounding use the original question, which limits query drift.

## Known Limitations

- The sparse retriever is PostgreSQL full-text search with `ts_rank`. It is **not** BM25 (no IDF weighting or length normalization).
- Plain sparse search requires all query terms to match, so long natural-language questions often get no sparse results. Keyword expansion uses OR matching to compensate.
- Rerank scores are raw model outputs: a correct chunk can score negative, and scores are only meaningful relative to each other, so there is no relevance cutoff on them. RRF scores reward agreement between searches, not relevance, so they must not be used as a cutoff either.
- The similarity threshold decides only whether to answer at all, not which chunks reach the LLM, and its default (0.8) is looser than the distance gap observed between relevant and off-topic content on the test documents.
- Query transformation adds one LLM call per question. It fails open only when the transformation call itself fails; if the answer call fails too, the request fails. HyDE passages may contain invented facts; they only steer retrieval and never reach the final answer.
- Reranking and query transformation were checked by hand on a small set of documents; their effect has not yet been measured (formal evaluation is Phase 13).
- Rechunking a document in the Chunking Lab discards its page numbers (stored text is flat); re-upload to restore page attribution.
- Uploading the same file twice creates duplicate chunks that compete for top-k slots; there is no deduplication yet.
- The first request after a restart is slow while local models load (embedding model, then the cross-encoder).
- Tests run against the development database.

## Project Structure

```
knowledgeflow-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entrypoint
│   │   ├── core/                 # config, logging
│   │   ├── db/                   # SQLAlchemy models, session, declarative base
│   │   ├── rag/                  # parsers, chunker, embeddings, llm, retriever (dense/sparse/RRF),
│   │   │                         # reranker, query_transform, pipeline
│   │   └── api/                  # route handlers (health, documents, query)
│   ├── alembic/                  # DB migrations
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/                  # Next.js App Router pages
│       ├── components/           # React components
│       └── lib/                  # API clients
└── docs/
```

## Git Checkpoints

Each verified phase is tagged: `phase-0-foundation`, `phase-1-basic-rag`, `phase-2-chunking`, `phase-3-metadata`, `phase-4-retrieval-lab`, `phase-5-hybrid-search`, `phase-6-reranking`, `phase-7-query-transformation`.

## Roadmap

This project is built in 17 sequential phases (0–16), each adding one RAG concept at a time, with Claude acting as architect/reviewer for every phase: foundation, basic RAG, chunking, metadata, retrieval debugging, hybrid search, reranking, query transformation, conversational RAG, multi-workspace knowledge spaces, multimodal RAG, agentic RAG (LangGraph), Graph RAG, formal evaluation (Recall@K, MRR, NDCG), an experimentation lab, productionization (auth, caching, observability), and RAG security. Every phase is verified — tested manually and via `pytest` — before the next begins.

## License

Personal learning project.