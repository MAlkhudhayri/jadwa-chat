# JadwaChat

AI powered analyst chat system built for Jadwa Investment. A production grade RAG (Retrieval Augmented Generation) platform that lets analysts query documents, time series data, and the web through a single conversational interface.

![Uploading jadwachat_techstack.drawio.png…]()


## Features

* **Multi Database Support** Create separate collections for different document sets
* **Smart Routing** LLM based intent classification routes queries to the right pipeline
* **Streaming Responses** Real time token by token generation via SSE
* **Source Citations** Every answer includes relevant source documents with similarity scores
* **File Upload** Drag and drop support for PDF, DOCX, TXT, MD, CSV, Excel
* **Docling Processing** Extracts text chunks and tables from documents automatically
* **Time Series Analytics** Rolling averages, correlations, top movers, growth rates
* **Web Search Fallback** Falls back to DuckDuckGo when internal data is insufficient
* **Conversation Memory** Persistent chat history with context aware follow ups
* **Bilingual** English and Arabic support
* **JWT Authentication** Secure user registration and login
* **Branded UI** Animated splash screen, Jadwa color palette, responsive design

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, Tailwind CSS, TypeScript |
| Backend | FastAPI, LangChain, Python 3.11 |
| Vector DB | Qdrant Cloud |
| Relational DB | PostgreSQL |
| LLM | OpenAI GPT 4o |
| Embeddings | OpenAI text embedding 3 large |
| Document Processing | Docling |
| Deployment | Railway, Docker |

## Architecture

```
                        ┌─────────────────────┐
                        │   Frontend (Next.js) │
                        │   Splash → Auth → UI │
                        └─────────┬───────────┘
                                  │
                                  ▼
                        ┌─────────────────────┐
                        │   Backend (FastAPI)  │
                        │                     │
                        │   JWT Auth Layer     │
                        │         │            │
                        │         ▼            │
                        │   Orchestrator       │
                        │   (LLM Classifier)   │
                        └──┬──────┬──────┬────┘
                           │      │      │
              ┌────────────┘      │      └────────────┐
              ▼                   ▼                    ▼
     ┌────────────────┐  ┌──────────────┐   ┌────────────────┐
     │ Document Query │  │  Data Query  │   │ General Query  │
     │                │  │              │   │                │
     │ Qdrant Vector  │  │ PostgreSQL   │   │ Web Search     │
     │ Search         │  │ Time Series  │   │ (DuckDuckGo)   │
     │                │  │ Analytics    │   │                │
     └────────────────┘  └──────────────┘   └────────────────┘
              │                   │                    │
              └───────────┬───────┘────────────────────┘
                          ▼
                 ┌────────────────┐
                 │  GPT 4o        │
                 │  Answer with   │
                 │  Citations     │
                 └────────────────┘
```

### Upload Flow

```
     User uploads file
            │
            ▼
     ┌──────────────┐
     │  Smart Router │
     │  (file type)  │
     └───┬──────┬────┘
         │      │
         ▼      ▼
   CSV/Excel   PDF/DOCX/TXT
      │            │
      │      ┌─────▼──────┐
      │      │  Docling    │
      │      │  Processor  │
      │      └──┬──────┬───┘
      │         │      │
      ▼         ▼      ▼
  PostgreSQL  Qdrant  PostgreSQL
  (time       (vector (extracted
   series)    embed)   tables)
```

## Quick Start

### Option 1: Railway (Production)

The app is deployed on Railway with three services:

* **Backend** FastAPI container on port 8080
* **Frontend** Next.js container on port 3000
* **PostgreSQL** Managed database

### Option 2: Local Development

#### Prerequisites
* Python 3.11+
* Node.js 20+
* Docker (for Qdrant)

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

## Usage

1. **Register / Login** Create an account or sign in
2. **Create a Database** Click "Add database" in the sidebar
3. **Upload Documents** Click "Upload documents" and drag files in
4. **Start Chatting** Type your question and JadwaChat will find answers
5. **All Databases** Select "All Databases" to search across every collection

## Environment Variables

### Backend

| Variable | Description |
|---|---|
| OPENAI_API_KEY | OpenAI API key |
| DATABASE_URL | PostgreSQL connection string |
| QDRANT_URL | Qdrant Cloud cluster URL |
| QDRANT_API_KEY | Qdrant Cloud API key |
| JWT_SECRET | Secret key for JWT tokens |
| ALLOWED_ORIGINS | Comma separated list of allowed frontend origins |

### Frontend

| Variable | Description |
|---|---|
| NEXT_PUBLIC_API_URL | Backend URL for API calls |

## API Documentation

Once the backend is running, visit:
* **Swagger UI**: http://localhost:8000/docs
* **ReDoc**: http://localhost:8000/redoc
