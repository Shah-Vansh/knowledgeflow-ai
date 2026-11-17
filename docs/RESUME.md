# KnowledgeFlow AI — resume & portfolio kit

Everything here is factual and can be checked against the repository. Pick the
version that fits the space you have, then put your own name, dates and links around it.

---

## 1. Resume entry (copy-paste)

**KnowledgeFlow AI — Enterprise Knowledge & Research Copilot** · *Personal project* · [github.com/Shah-Vansh/knowledgeflow-ai](https://github.com/Shah-Vansh/knowledgeflow-ai)
*Python, FastAPI, PostgreSQL + pgvector, SQLAlchemy/Alembic, LangGraph, sentence-transformers, Next.js, TypeScript, Tailwind CSS*

- Built a full-stack retrieval-augmented generation (RAG) platform that answers questions only from a team's own documents, with page-level citations, across 17 incremental phases.
- Implemented hybrid retrieval (pgvector dense search + PostgreSQL full-text search fused with Reciprocal Rank Fusion), a local cross-encoder reranker, LLM query transformation (rewrite, expansion, multi-query, HyDE) and conversational follow-up rewriting.
- Added multimodal ingestion (table extraction, OCR for scanned pages and images), a verified knowledge graph whose every relation must be backed by its source passage, and a LangGraph agent that routes questions to search, graph, metadata or a sandboxed calculator.
- Built an evaluation harness (hit@k, recall@k, precision@k, MRR, NDCG, LLM-judged faithfulness) and an experimentation lab that compares configurations with paired bootstrap confidence intervals.
- Secured the API with Argon2id passwords, revocable JWTs, viewer/editor/owner workspace roles enforced by one deny-by-default policy table over all 49 routes, rate limiting, prompt-injection fencing and output sanitization.
- Productionized with a PostgreSQL job queue (`FOR UPDATE SKIP LOCKED`) and retrying workers, duplicate-upload detection, an embedding cache, JSON logs with secret redaction, readiness probes and Prometheus metrics; covered by 548 automated tests and 39 mutation checks.

### Short version (3 bullets)

- Built a full-stack RAG platform (FastAPI, PostgreSQL/pgvector, Next.js) with hybrid search, cross-encoder reranking, a knowledge graph and a LangGraph agent, answering only from uploaded documents with citations.
- Measured retrieval quality with a custom evaluation harness (recall@k, MRR, NDCG) and an experimentation lab using paired bootstrap significance tests.
- Hardened it for production: role-based access control over every route, revocable JWT auth, prompt-injection defences, a PostgreSQL job queue with retrying workers, structured logging and metrics; 548 tests.

### One-liner (for a projects list or LinkedIn headline)

> Full-stack RAG copilot — hybrid search, reranking, knowledge graph and agent over private documents, with evaluation, role-based security and a production job queue (FastAPI · PostgreSQL/pgvector · Next.js).

---

## 2. Skills this project demonstrates

| Area | Evidence in the repo |
|---|---|
| **Retrieval / IR** | Dense + full-text hybrid search, RRF fusion, cross-encoder reranking, query transformation, grounding gate (`backend/app/rag/retriever.py`, `pipeline.py`) |
| **LLM engineering** | Grounded prompts, conversation-aware question rewriting, LLM router with strict output validation, LLM-as-judge with stated bias (`rag/conversation.py`, `agent/`, `rag/evaluation.py`) |
| **Evaluation & statistics** | Evidence-labelled golden sets; hit/recall/precision@k, MRR, NDCG; paired bootstrap confidence intervals (`rag/evaluation.py`, `rag/experiments.py`) |
| **Backend** | FastAPI, SQLAlchemy, 11 Alembic migrations, PostgreSQL row locking, background workers (`app/jobs/`) |
| **Security** | Argon2id, JWT with explicit algorithms and versioned revocation, deny-by-default authorization, 404 masking against id probing, rate limits, upload signature checks, prompt fencing, security headers (`app/core/access.py`, `security.py`, `http.py`, `rag/safety.py`) |
| **Reliability / ops** | Job queue with backoff and stale-job recovery, readiness vs liveness probes, Prometheus metrics, JSON logs with redaction, startup configuration check |
| **Testing** | 548 pytest tests against a real PostgreSQL test database, an access-control matrix over every route × 5 user types, 39 mutation checks proving the tests catch broken security code |
| **Frontend** | Next.js App Router, TypeScript, Tailwind design system, app shell with client-side navigation and global workspace state, background-job progress polling |

**Keywords for ATS filters:** RAG, Retrieval-Augmented Generation, LLM, LangGraph, vector database, pgvector, embeddings, semantic search, hybrid search, reranking, cross-encoder, knowledge graph, OCR, FastAPI, Python, PostgreSQL, SQLAlchemy, Alembic, JWT, RBAC, Next.js, React, TypeScript, Tailwind CSS, pytest, Prometheus, observability.

---

## 3. Numbers you can quote

| Metric | Value |
|---|---|
| Build phases | 17 (0–16), each tested before the next |
| API routes | 49, every one covered by the access-policy table |
| Database migrations | 11 |
| Automated tests | 548 (547 pass + 1 that needs a live LLM key) |
| Mutation checks | 39, all caught |
| Backend / frontend code | ~7,700 lines Python, ~5,900 lines TypeScript |
| App pages | 14, in one app shell |
| Running cost | Local embeddings, reranker and OCR; only answer generation calls an LLM (Groq free tier) |

---

## 4. Interview talking points

Short stories that show judgement, not just features. Each one has a concrete trade-off.

1. **Why hybrid search, and why RRF?** Dense vectors catch paraphrases but miss exact IDs and numbers; full-text search is the opposite. Their scores live on incomparable scales (cosine distance vs `ts_rank`), so I fuse by *rank position* with Reciprocal Rank Fusion instead of normalizing scores. Honest caveat: PostgreSQL full-text search is not BM25 (no IDF or length normalization).
2. **Reranking can only reorder.** The cross-encoder is accurate but too slow to run over every chunk, so it scores a 20-candidate pool. It can't rescue a passage retrieval never found — which is why I measure recall@k *before* reranking separately.
3. **Evaluation labels that survive re-chunking.** Golden-set answers are labelled with evidence *text*, not chunk ids, so one golden set can score any chunking strategy. If a chunk boundary splits the evidence, recall drops — exactly the failure the metric should expose.
4. **Saying "not significant".** The experiment lab reports paired bootstrap intervals; with a small golden set most differences aren't significant, and the UI says so instead of declaring a winner.
5. **A knowledge graph that can't hallucinate links.** The LLM proposes entities and relations, but each is kept only if its source chunk contains the names word-for-word, and every relation stores the passage it came from.
6. **Deny by default, provably.** Every route must appear in one policy table or the app refuses to start; a test matrix calls all routes as five kinds of users. Non-members get the same 404 as a missing record, so ids can't be probed. I mutation-tested the security code: deliberately breaking each check makes a test fail.
7. **A job queue without Redis.** Uploads can be queued in PostgreSQL itself; workers claim jobs with `FOR UPDATE SKIP LOCKED`, so several workers never take the same job (tested with 6 threads × 24 jobs). The document and its job commit in one transaction, failed jobs back off exponentially, and jobs from crashed workers are recovered.
8. **Prompt injection is mitigated, not solved.** Retrieved passages are fenced as untrusted data and the model's output is sanitized (no images, scripts or `javascript:` links). I document that this reduces risk but can't be proven safe against a capable model.
9. **Race conditions.** "A workspace must keep one owner" was a read-then-write race; owner rows are now locked (`SELECT … FOR UPDATE`) during the check, with a test that proves a concurrent change has to wait.

---

## 5. Portfolio / GitHub blurb

**KnowledgeFlow AI** is an enterprise knowledge copilot: upload PDFs, scans, images and text into private workspaces, then chat with them and get answers that cite their sources. Under the hood it combines hybrid vector + full-text search, a cross-encoder reranker, a verified knowledge graph and a LangGraph agent, and it ships with an evaluation harness and an experimentation lab to *measure* retrieval quality rather than guess. It is built for real use: role-based access control, revocable logins, prompt-injection defences, a PostgreSQL-backed job queue, structured logs and metrics, and 548 automated tests.

**Suggested GitHub "About" line:** Full-stack RAG copilot: hybrid search, reranking, knowledge graph & agent over private documents — with evaluation, RBAC and a production job queue. FastAPI · PostgreSQL/pgvector · Next.js

**Suggested topics:** `rag` `llm` `retrieval-augmented-generation` `fastapi` `pgvector` `postgresql` `nextjs` `langgraph` `knowledge-graph` `semantic-search`

---

## 6. Demo script (3 minutes)

1. **Dashboard** — show the sidebar, the workspace switcher and the counts.
2. **Upload** a PDF and a photo of a printed page; open **Inspector** to show tables and OCR text that were extracted.
3. **Chat** — ask a question, then a follow-up like "when did it open?"; point at the cited sources.
4. Ask something the documents don't cover — it refuses instead of inventing an answer.
5. **Retrieval lab** — the same question in dense vs full-text vs hybrid, then switch the reranker on and watch ranks move.
6. **Evaluation / Experiments** — a golden set's recall@5 and MRR, and a variant comparison with confidence intervals.
7. Close with security: sign in as a viewer and show that delete actions are refused.
