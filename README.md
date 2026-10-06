KnowledgeFlow AI

Enterprise Knowledge & Research Copilot — an AI knowledge platform built progressively, phase by phase, to learn Retrieval-Augmented Generation (RAG) from beginner to production level.

Current Status: Phase 4 — Retrieval Laboratory ✅

A working RAG pipeline with configurable chunking, page-level source attribution, document lifecycle management, and a dedicated retrieval debugging interface — built and verified through four phases, each tagged and tested before moving to the next.

Tech Stack
Frontend: Next.js, React, TypeScript, Tailwind CSS
Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic
Database: PostgreSQL + pgvector (compiled from source)
Embeddings: Local, free — sentence-transformers (all-MiniLM-L6-v2, 384-dim), runs entirely on-device, no API key or cost
LLM: Groq (openai/gpt-oss-20b), free tier

Note: This project runs natively on Windows (no Docker). Docker was evaluated but dropped due to a Windows image on this machine that doesn't support WSL2/virtualization required by Docker Desktop. pgvector was compiled from source using Visual Studio Build Tools since no prebuilt Windows binary exists.

Setup
1. PostgreSQL + pgvector
Install PostgreSQL 16+ locally: https://www.postgresql.org/download/windows/
Compile and install pgvector from source (requires Visual Studio Build Tools with C++ support):
  call "<path to>\VC\Auxiliary\Build\vcvars64.bat"
  set "PGROOT=C:\Program Files\PostgreSQL\<version>"
  git clone https://github.com/pgvector/pgvector.git
  cd pgvector
  nmake /F Makefile.win
  nmake /F Makefile.win install
Create the project database and enable the extension:
sql
  CREATE DATABASE knowledgeflow;
  \c knowledgeflow
  CREATE EXTENSION IF NOT EXISTS vector;
2. Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

Copy the example env file and edit it:

copy .env.example .env

Fill in backend/.env:

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

Apply database migrations:

alembic upgrade head

Run the backend:

uvicorn app.main:app --reload

Backend runs at http://localhost:8000

3. Frontend

Open a new terminal:

cd frontend
npm install
copy .env.example .env

frontend/.env:

NEXT_PUBLIC_API_URL=http://localhost:8000

Run the frontend:

npm run dev

Frontend runs at http://localhost:3000

4. Verify everything is connected
curl http://localhost:8000/health

Expected: {"status": "ok", "db_connected": true, "environment": "development"}

Open http://localhost:3000 — you should see a green "Backend Connected" status.

Run Backend Tests
cd backend
venv\Scripts\activate
pytest

One test (test_rag_pipeline_api.py) requires a GROQ_API_KEY exported as a shell environment variable to run (it calls the live LLM); it skips cleanly otherwise.

Features by Phase
Phase	Feature	Status
0	Foundation — FastAPI + Next.js + PostgreSQL, health check	✅
1	Basic RAG — upload, chunk, embed, retrieve, grounded answer	✅
2	Chunking Laboratory — configurable strategies (fixed-size, recursive, sentence), overlap, side-by-side comparison	✅
3	Document & Metadata Management — page-level source attribution, soft delete with cascade, document-scoped queries	✅
4	Retrieval Laboratory — raw ranked retrieval debugging, configurable k/threshold, live threshold recompute	✅
5–16	Hybrid Search, Reranking, Query Transformation, Conversational RAG, Multi-Workspace, Multimodal RAG, Agentic RAG, Graph RAG, Evaluation, Experimentation Lab, Productionization, Security	🔜
Application Pages
/ — health check / connection status
/upload — upload PDF/TXT documents with optional chunking configuration
/query — ask questions, optionally scoped to specific documents, with source attribution
/documents — manage uploaded documents (view metadata, delete)
/chunking-lab — compare chunking strategies side by side on the same document
/retrieval-lab — debug raw retrieval: ranked candidates, distances, configurable k/threshold
Architecture
Document Upload (PDF/TXT)
      ↓
Page-aware Text Extraction
      ↓
Chunking (fixed_size | recursive | sentence, configurable)
      ↓
Embedding (local, sentence-transformers)
      ↓
PostgreSQL + pgvector
      ↓
Query → Embed → Cosine Similarity Search (optionally document-scoped)
      ↓
Threshold Check → Context Assembly
      ↓
LLM (Groq) → Grounded Answer + Deduplicated Sources

Both EmbeddingProvider and LLMProvider are abstracted behind interfaces (app/rag/embeddings.py, app/rag/llm.py) — the project originally used OpenAI for both and was swapped to local embeddings + Groq mid-build with zero changes to any other file, which is the abstraction proving itself.

Project Structure
knowledgeflow-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entrypoint
│   │   ├── core/                 # config, logging
│   │   ├── db/                   # SQLAlchemy models, session, declarative base
│   │   ├── rag/                  # parsers, chunker, embeddings, llm, retriever, pipeline
│   │   └── api/                  # route handlers (health, documents, query)
│   ├── alembic/                  # DB migrations
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/                  # Next.js App Router pages
│       ├── components/           # React components
│       └── lib/                  # API clients
└── docs/
Git Checkpoints

Each verified phase is tagged: phase-0-foundation, phase-1-basic-rag, phase-2-chunking, phase-3-metadata, phase-4-retrieval-lab.

Roadmap

This project is built in 17 sequential phases (0–16), each adding one RAG concept at a time, with Claude acting as architect/reviewer for every phase: foundation, basic RAG, chunking, metadata, retrieval debugging, hybrid search, reranking, query transformation, conversational RAG, multi-workspace knowledge spaces, multimodal RAG, agentic RAG (LangGraph), Graph RAG, formal evaluation (Recall@K, MRR, NDCG), an experimentation lab, productionization (auth, caching, observability), and RAG security. Every phase is verified — tested manually and via pytest — before the next begins.

License

Personal learning project.