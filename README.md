# chatiitd-rag Backend

FastAPI backend providing REST endpoints for authentication (DevClub OAuth), chat management, AI agent invocation, and admin document management with Qdrant vector-database integration.

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Start Qdrant first (required):

```bash
docker compose up qdrant
```

Run the backend:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 3000 --reload
```

## Docker Setup

Build and start the full stack (backend + Qdrant):

```bash
docker compose up --build
```

- Place any Qdrant snapshot files in `snapshots/` before starting — they are mounted at `/qdrant/snapshots` in the container for restore operations.
- FastAPI backend: `http://localhost:3000`
- Qdrant API: `http://localhost:6333` (dashboard at `/dashboard`)
- Persistent volumes: `backend-data` (SQLite) and `qdrant-storage` (Qdrant collections)

## Manual Run (without Docker)

1. Start Qdrant:

```bash
sudo docker run -d -p 6333:6333 -p 6334:6334 --restart unless-stopped qdrant/qdrant
```

2. Upload snapshots at `http://localhost:6333/dashboard`.

3. Create `.env` in the project root (see Environment Variables below).

4. Install and run:

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 3000
```

## Environment Variables

Create a `.env` file in the project root:

```bash
# Google Gemini LLM (REQUIRED)
GOOGLE_API_KEY=your_google_api_key_here

# DevClub OAuth (REQUIRED)
CLIENT_ID=your_devclub_client_id_here
CLIENT_SECRET=your_devclub_client_secret_here

# JWT
JWT_SECRET=change-me-in-prod
JWT_EXP_MINUTES=1440

# Database
DATABASE_URL=sqlite:///messages.db

# Qdrant
QDRANT_URL=http://localhost:6333

# Optional: bypass auth for demos
DEMO_MODE=false
```

| Variable          | Description                      | Default                 |
| ----------------- | -------------------------------- | ----------------------- |
| `GOOGLE_API_KEY`  | Gemini LLM API key               | —                       |
| `CLIENT_ID`       | DevClub OAuth client ID          | —                       |
| `CLIENT_SECRET`   | DevClub OAuth client secret      | —                       |
| `JWT_SECRET`      | Secret for signing JWTs          | `change-me-in-prod`     |
| `JWT_EXP_MINUTES` | JWT expiration in minutes        | `1440`                  |
| `DATABASE_URL`    | SQLModel DB URL                  | `sqlite:///messages.db` |
| `QDRANT_URL`      | Qdrant server URL                | `http://localhost:6333` |
| `DEMO_MODE`       | Bypass auth for demos            | `false`                 |

## API Documentation

Interactive documentation is available once the server is running:

| URL | Description |
| --- | --- |
| `http://localhost:3000/docs` | Standard Swagger UI |
| `http://localhost:3000/docs-advanced` | Enhanced Swagger UI (persistent auth, deep linking) |
| `http://localhost:3000/redoc` | ReDoc (clean, readable format) |
| `http://localhost:3000/openapi.json` | Raw OpenAPI 3.0 schema |

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

- Use Secrets Manager or Parameter Store for `JWT_SECRET`, `CLIENT_ID`, `CLIENT_SECRET`.
- Use managed PostgreSQL (RDS or similar) for production DB.
- Ensure Qdrant is reachable from the backend (Qdrant Cloud or self-hosted on ECS).
- The `uploads/` directory should be on a persistent volume or object storage (S3) in production.
