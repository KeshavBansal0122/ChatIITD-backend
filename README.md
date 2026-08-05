# chatiitd-rag Backend

FastAPI backend providing REST endpoints for authentication (DevClub OAuth), chat management, AI agent invocation, and admin document management with Qdrant vector-database integration.

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in secrets
```

Start infra (Postgres + Qdrant + snapshot restore):

```bash
docker compose up -d postgres qdrant
docker compose up qdrant-init
```

Run the backend:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Docker Setup

Build and start the full backend stack (Postgres + Qdrant + restore + API):

```bash
cp .env.example .env   # fill in secrets
docker compose up --build
```

- Place any Qdrant snapshot files in `snapshots/` before starting — `qdrant-init` mounts them at `/snapshots` and restores into Qdrant.
- FastAPI backend: `http://localhost:8000`
- Qdrant API: `http://localhost:6333` (dashboard at `/dashboard`)
- Postgres: `localhost:5432` (`chatiitd` / `chatiitd_dev`)
- Persistent volumes: `postgres-data`, `qdrant-storage`, `backend-uploads`

For the SPA, use `frontend/docker-compose.yml` (serves on `http://localhost:3000`). Backend CORS defaults allow both Vite (`:5173`) and Docker frontend (`:3000`).

## Manual Run (without full Docker stack)

1. Start Postgres + Qdrant:

```bash
docker compose up -d postgres qdrant
docker compose up qdrant-init
```

2. Create `.env` in the project root (see Environment Variables below / `.env.example`).

3. Install and run:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```bash
# OpenRouter LLM (REQUIRED)
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=openai/gpt-oss-120b:free

# DevClub OAuth (REQUIRED)
CLIENT_ID=your_devclub_client_id_here
CLIENT_SECRET=your_devclub_client_secret_here

# Database (Postgres recommended)
DATABASE_URL=postgresql://chatiitd:chatiitd_dev@localhost:5432/chatiitd

# Qdrant
QDRANT_URL=http://localhost:6333

# CORS / URLs
FRONTEND_URL=http://localhost:5173,http://localhost:3000
BACKEND_URL=http://localhost:8000

# Optional: bypass auth for demos
DEMO_MODE=false
```

| Variable             | Description                     | Default                 |
| -------------------- | ------------------------------- | ----------------------- |
| `OPENROUTER_API_KEY` | OpenRouter LLM API key          | —                       |
| `OPENROUTER_MODEL`   | OpenRouter model id             | see `.env.example`      |
| `CLIENT_ID`          | DevClub OAuth client ID         | —                       |
| `CLIENT_SECRET`      | DevClub OAuth client secret     | —                       |
| `DATABASE_URL`       | SQLModel DB URL                 | Postgres URL above      |
| `QDRANT_URL`         | Qdrant server URL               | `http://localhost:6333` |
| `FRONTEND_URL`       | CORS origin(s), comma-separated | `http://localhost:5173` |
| `BACKEND_URL`        | Public backend URL              | `http://localhost:8000` |
| `DEMO_MODE`          | Bypass auth for demos           | `false`                 |

## API Documentation

Interactive documentation is available once the server is running:

| URL | Description |
| --- | --- |
| `http://localhost:8000/docs` | Standard Swagger UI |
| `http://localhost:8000/docs-advanced` | Enhanced Swagger UI (persistent auth, deep linking) |
| `http://localhost:8000/redoc` | ReDoc (clean, readable format) |
| `http://localhost:8000/openapi.json` | Raw OpenAPI 3.0 schema |

## Authentication

The API uses [DevClub OAuth](https://oauth.devclub.in/) for authentication.

**Setup**: Register your application at https://oauth.devclub.in/ to get `CLIENT_ID` and `CLIENT_SECRET`.

**Flow**:
```
GET /auth/signin-url?redirect_uri=<callback_url>
→ Returns DevClub OAuth signin URL
→ Redirect user to signin URL
→ User authenticates with DevClub
→ DevClub redirects back with code & state
POST /auth/callback { code, state }
→ Returns JWT { access_token, token_type: "bearer" }
```

All protected endpoints require: `Authorization: Bearer <access_token>`

**Testing in Swagger**: Get a token via `/auth/signin-url` → `/auth/callback`, then click "Authorize" in Swagger UI and enter `Bearer <token>`.

### User Roles

Every user has a `role` field:

- **`user`** (default) — access to chat endpoints only.
- **`admin`** — additionally access `/admin/*` document management endpoints.

To promote a user to admin:

```sql
UPDATE user SET role='admin' WHERE email='admin@example.com';
```

## API Categories

Full request/response schemas are in the Swagger docs. Summary:

| Category | Endpoints |
| -------- | --------- |
| System | `GET /health` |
| Auth | `GET /auth/signin-url`, `POST /auth/callback` |
| Chats | `POST /chats`, `GET /chats`, `GET /chats/{id}`, `POST /chats/new`, `DELETE /chats/{id}` |
| Messages | `POST /chats/{id}/messages`, `GET /chats/{id}/messages` |
| Admin | `POST /admin/documents`, `GET /admin/documents`, `GET /admin/documents/{id}`, `DELETE /admin/documents/{id}` |

### Common Error Codes

| Code | Description |
| ---- | ----------- |
| `400` | Bad request (malformed body, wrong file type) |
| `401` | Unauthorized — missing or invalid JWT |
| `403` | Forbidden — insufficient role |
| `404` | Resource not found |
| `500` | Internal server error |
| `502` | Agent/upstream service failed |

### Admin Document Management

`/admin/*` endpoints require `role = "admin"`. Non-admin requests return `403`.

`POST /admin/documents` accepts `multipart/form-data` with a PDF `file` and optional `description`. The server chunks the PDF, embeds the chunks, and stores them in the Qdrant `documents` collection.

Each Qdrant point payload has:
```json
{
  "content": "chunk text...",
  "metadata": {
    "file_id": 1,
    "file_name": "doc.pdf",
    "description": "...",
    "upload_date": "...",
    "page": 3,
    "headers": ["Section 1"],
    "header_id": 5,
    "type": "text",
    "chunk_index": 0,
    "source_file": "/path/to/stored/file.pdf"
  }
}
```

`DELETE /admin/documents/{id}` removes all vector embeddings from Qdrant, deletes the PDF from disk, and removes the DB record.

## Production Notes

- Use Secrets Manager or Parameter Store for `CLIENT_ID`, `CLIENT_SECRET`, and `OPENROUTER_API_KEY`.
- Use managed PostgreSQL (RDS or similar) for production DB.
- Ensure Qdrant is reachable from the backend (Qdrant Cloud or self-hosted on ECS).
- The `uploads/` directory should be on a persistent volume or object storage (S3) in production (`backend-uploads` volume in Compose).
