# JadwaChat — AI Document Assistant

A production-grade RAG (Retrieval-Augmented Generation) chat system for querying multiple document databases. Built for Jadwa Investment.

## Features

- **Multi-Database Support** — Create separate collections for different document sets
- **Streaming Responses** — Real-time token-by-token generation via SSE
- **Source Citations** — Every answer includes relevant source documents with scores
- **File Upload** — Drag-and-drop support for PDF, DOCX, TXT, MD, CSV
- **Conversation History** — Persistent chat history with context-aware follow-ups
- **Bilingual** — English and Arabic support
- **Beautiful UI** — Jadwa-branded interface with responsive design

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14, Tailwind CSS, TypeScript |
| **Backend** | FastAPI, LangChain, Python 3.11 |
| **Vector DB** | Qdrant |
| **LLM** | OpenAI GPT-4o |
| **Embeddings** | OpenAI text-embedding-3-large |
| **Storage** | SQLite (chat history) |
| **Deployment** | Docker Compose |

## Architecture

```
Frontend (Next.js)  →  Backend (FastAPI)  →  Qdrant (vectors)
                                          →  OpenAI (LLM + embeddings)
                                          →  SQLite (history)
```

---

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# 1. Clone and configure
cd rag-multi-database-chat
cp backend/.env.example backend/.env
# Edit backend/.env and add your OPENAI_API_KEY

# 2. Launch everything
docker compose up -d

# 3. Open the app
open http://localhost:3000
```

### Option 2: Local Development

#### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker (for Qdrant)

#### 1. Start Qdrant
```bash
docker run -d -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

#### 2. Start Backend
```bash
cd backend
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

#### 3. Start Frontend
```bash
cd frontend
npm install
npm run dev
```

#### 4. Open the App
Navigate to **http://localhost:3000**

---

## Usage

1. **Create a Database** — Click "Add database" in the sidebar
2. **Upload Documents** — Click "Upload documents" and drag files in
3. **Start Chatting** — Type your question and JadwaChat will find answers

## API Documentation

Once the backend is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Project Structure

```
rag-multi-database-chat/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI route handlers
│   │   │   ├── chat.py        # Chat & conversation endpoints
│   │   │   ├── documents.py   # Document upload & management
│   │   │   └── collections.py # Collection CRUD
│   │   ├── core/
│   │   │   └── database.py    # SQLite models & session management
│   │   ├── models/
│   │   │   └── schemas.py     # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── rag.py         # RAG pipeline (retrieve → augment → generate)
│   │   │   ├── vectorstore.py # Qdrant operations
│   │   │   └── history.py     # Conversation history management
│   │   ├── config.py          # App configuration
│   │   └── main.py            # FastAPI app factory
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/               # Next.js App Router
│   ├── components/        # React components
│   ├── lib/               # API client & utilities
│   ├── types/             # TypeScript types
│   ├── package.json
│   └── Dockerfile
└── docker-compose.yml
```
