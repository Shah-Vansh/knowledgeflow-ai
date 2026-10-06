KnowledgeFlow AI

Enterprise Knowledge & Research Copilot — an AI knowledge platform built progressively, phase by phase, to learn Retrieval-Augmented Generation (RAG) from beginner to production level.

Current Status: Phase 0 — Foundation ✅

A working full-stack skeleton with zero RAG logic: Next.js frontend, FastAPI backend, PostgreSQL database, connected end-to-end via a health check.

Tech Stack
Frontend: Next.js, React, TypeScript, Tailwind CSS
Backend: Python, FastAPI, Pydantic, SQLAlchemy
Database: PostgreSQL (pgvector extension added in Phase 1)

Note: This project runs natively on Windows (no Docker). Docker was evaluated but dropped due to a Windows image on this machine that doesn't support WSL2/virtualization required by Docker Desktop.

Setup
1. PostgreSQL
Install PostgreSQL 16 locally: https://www.postgresql.org/download/windows/
During install, set a password for the postgres superuser and keep it — you'll need it below.
Create the project database using psql (SQL Shell, installed alongside Postgres) or pgAdmin:
sql
  CREATE DATABASE knowledgeflow;
2. Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

Copy the example env file and edit it:

copy .env.example .env

Open backend/.env and set your database URL:

DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/knowledgeflow
ENVIRONMENT=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000

Run the backend:

uvicorn app.main:app --reload

Backend runs at http://localhost:8000

3. Frontend

Open a new terminal:

cd frontend
npm install
copy .env.example .env

frontend/.env should contain:

NEXT_PUBLIC_API_URL=http://localhost:8000

Run the frontend:

npm run dev

Frontend runs at http://localhost:3000

4. Verify everything is connected
curl http://localhost:8000/health

Expected response:

json
{"status": "ok", "db_connected": true, "environment": "development"}

Open http://localhost:3000 in your browser — you should see a green "Backend Connected" box showing the same JSON.

Run Backend Tests
cd backend
venv\Scripts\activate
pytest
Project Structure
knowledgeflow-ai/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app entrypoint
│   │   ├── core/             # config, logging
│   │   ├── db/                # SQLAlchemy session, declarative base
│   │   └── api/               # route handlers
│   ├── alembic/               # DB migrations
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/                # Next.js App Router pages
│       ├── components/         # React components
│       └── lib/                # API client
└── docs/
Roadmap

This project is built in 17 sequential phases (0–16), each adding one RAG concept at a time — chunking, metadata, retrieval, hybrid search, reranking, query transformation, conversational RAG, multimodal RAG, agentic RAG, Graph RAG, evaluation, experimentation, productionization, and security. Each phase is tagged in git once verified (e.g. phase-0-foundation).

License

Personal learning project.