# Agentic Chatbot Backend

This FastAPI backend provides REST endpoints for authentication (DevClub OAuth), chat management, storing messages, invoking the chatbot agent, and **admin document management** with Qdrant vector-database integration.

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the backend:

```bash
uvicorn backend.main:app --reload
```

> **Note:** Qdrant must be running. Start it with `docker compose up qdrant` from the project root.

## Environment Variables

| Variable          | Description                      | Default                 |
| ----------------- | -------------------------------- | ----------------------- |
| `JWT_SECRET`      | Secret for signing access tokens | `change-me-in-prod`     |
| `JWT_EXP_MINUTES` | JWT expiration in minutes        | `1440`                  |
| `DATABASE_URL`    | SQLModel DB URL                  | `sqlite:///messages.db` |
| `CLIENT_ID`       | DevClub OAuth client ID          | —                       |
| `CLIENT_SECRET`   | DevClub OAuth client secret      | —                       |
| `QDRANT_URL`      | Qdrant server URL                | `http://localhost:6333` |

## Auth Flow

1. Frontend initiates OAuth with DevClub and gets an authorization code + state.
2. Frontend POSTs `{ code, state }` to `POST /auth/callback`.
3. Backend validates with DevClub OAuth server, creates/finds the user, and returns a signed JWT.
4. All subsequent requests use `Authorization: Bearer <access_token>`.

### User Roles

Every user has a `role` field:

- **`user`** (default) — can access chat endpoints only.
- **`admin`** — can additionally access `/admin/*` endpoints.

To promote a user to admin, run:

```sql
UPDATE user SET role='admin' WHERE email='admin@example.com';
```

---

## API Reference

### Common Headers

```
Authorization: Bearer <access_token>
```

### Common Error Codes

| Code  | Description                                         |
| ----- | --------------------------------------------------- |
| `400` | Bad request (malformed body, wrong file type, etc.) |
| `401` | Unauthorized — missing or invalid JWT               |
| `403` | Forbidden — user does not have the required role    |
| `404` | Resource not found or does not belong to user       |
| `500` | Internal server error                               |
| `502` | Agent/upstream service failed                       |

---

### Authentication

#### `POST /auth/callback`

Exchange a DevClub OAuth authorization code for a JWT.

**Request Body:**

```json
{
  "code": "string",
  "state": "string"
}
```

**Response `200`:**

```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

| Error | Detail                |
| ----- | --------------------- |
| `400` | Missing code or state |
| `401` | Authentication failed |

---

### Chats

All chat endpoints require `Authorization: Bearer <token>`.

#### `POST /chats`

Create an empty chat.

**Request Body:**

```json
{
  "title": "string | null"
}
```

**Response `200`:**

```json
{
  "id": 1,
  "user_id": 1,
  "title": "string | null",
  "created_at": "2026-02-19T10:00:00"
}
```

---

#### `GET /chats`

List all chats for the authenticated user (newest first).

**Response `200`:**

```json
[
  {
    "id": 1,
    "user_id": 1,
    "title": "string | null",
    "created_at": "2026-02-19T10:00:00"
  }
]
```

---

#### `GET /chats/{chat_id}`

Get a single chat by ID.

**Response `200`:**

```json
{
  "id": 1,
  "user_id": 1,
  "title": "string | null",
  "created_at": "2026-02-19T10:00:00"
}
```

| Error | Detail                                    |
| ----- | ----------------------------------------- |
| `404` | Chat not found or does not belong to user |

---

#### `POST /chats/new`

Create a new chat and send the first message. Returns the chat, the assistant's response, and a title.

**Request Body:**

```json
{
  "content": "string"
}
```

**Response `200`:**

```json
{
  "chat": {
    "id": 1,
    "user_id": 1,
    "title": "Chat Title",
    "created_at": "2026-02-19T10:00:00"
  },
  "message": {
    "id": 1,
    "chat_id": 1,
    "sender": "assistant",
    "content": "string",
    "created_at": "2026-02-19T10:00:01"
  },
  "title": "Chat Title"
}
```

| Error | Detail                  |
| ----- | ----------------------- |
| `502` | Agent failed to respond |

---

#### `DELETE /chats/{chat_id}`

Delete a chat and all its messages.

**Response:** `204 No Content`

| Error | Detail                                    |
| ----- | ----------------------------------------- |
| `404` | Chat not found or does not belong to user |

---

### Messages

#### `POST /chats/{chat_id}/messages`

Send a message to the agent in an existing chat. The agent response is stored and returned.

**Request Body:**

```json
{
  "content": "string"
}
```

**Response `200`:**

```json
{
  "id": 2,
  "chat_id": 1,
  "sender": "assistant",
  "content": "string",
  "created_at": "2026-02-19T10:00:02"
}
```

| Error | Detail                  |
| ----- | ----------------------- |
| `404` | Chat not found          |
| `502` | Agent failed to respond |

---

#### `GET /chats/{chat_id}/messages`

List all messages in a chat (chronological order).

**Response `200`:**

```json
[
  {
    "id": 1,
    "chat_id": 1,
    "sender": "user",
    "content": "string",
    "created_at": "2026-02-19T10:00:00"
  }
]
```

| Error | Detail         |
| ----- | -------------- |
| `404` | Chat not found |

---

### Admin — Document Management

All `/admin/*` endpoints require **admin role** (`role = "admin"`) in addition to a valid JWT.
Non-admin users will receive `403 Forbidden`.

#### `POST /admin/documents`

Upload a PDF document. The server will chunk the PDF, embed the chunks, and store them in the Qdrant `documents` collection.

**Request:** `multipart/form-data`

| Field         | Type       | Required | Description                                |
| ------------- | ---------- | -------- | ------------------------------------------ |
| `file`        | file (PDF) | ✅       | The PDF file to upload                     |
| `description` | string     | ❌       | Admin-supplied description (default: `""`) |

**Response `200`:**

```json
{
  "document": {
    "id": 1,
    "original_name": "policy_doc.pdf",
    "description": "Internal policy document for OCS",
    "file_size": 204800,
    "chunk_count": 42,
    "uploaded_by": 1,
    "created_at": "2026-02-19T10:30:00"
  },
  "message": "Successfully uploaded and indexed 42 chunks"
}
```

**Qdrant Point Metadata Schema:**
Each chunk stored in Qdrant has the following payload structure:

```json
{
  "content": "chunk text...",
  "metadata": {
    "file_id": 1,
    "file_name": "policy_doc.pdf",
    "description": "Internal policy document",
    "upload_date": "2026-02-19T10:30:00",
    "page": 3,
    "headers": ["Section 1", "1.2 Eligibility"],
    "header_id": 5,
    "type": "text",
    "chunk_index": 0,
    "source_file": "/path/to/stored/file.pdf"
  }
}
```

| Error | Detail                                           |
| ----- | ------------------------------------------------ |
| `400` | Only PDF files are accepted                      |
| `403` | Admin access required                            |
| `500` | Failed to chunk PDF / Failed to store embeddings |

---

#### `GET /admin/documents`

List all uploaded documents (newest first).

**Response `200`:**

```json
[
  {
    "id": 1,
    "original_name": "policy_doc.pdf",
    "description": "Internal policy document",
    "file_size": 204800,
    "chunk_count": 42,
    "uploaded_by": 1,
    "created_at": "2026-02-19T10:30:00"
  }
]
```

| Error | Detail                |
| ----- | --------------------- |
| `403` | Admin access required |

---

#### `GET /admin/documents/{doc_id}`

Get details of a single uploaded document.

**Response `200`:**

```json
{
  "id": 1,
  "original_name": "policy_doc.pdf",
  "description": "Internal policy document",
  "file_size": 204800,
  "chunk_count": 42,
  "uploaded_by": 1,
  "created_at": "2026-02-19T10:30:00"
}
```

| Error | Detail                |
| ----- | --------------------- |
| `403` | Admin access required |
| `404` | Document not found    |

---

#### `DELETE /admin/documents/{doc_id}`

Delete a document. This will:

1. Remove all associated vector embeddings from the Qdrant `documents` collection
2. Delete the stored PDF file from disk
3. Remove the document record from the database

**Response:** `204 No Content`

| Error | Detail                   |
| ----- | ------------------------ |
| `403` | Admin access required    |
| `404` | Document not found       |
| `500` | Failed to remove vectors |

---

## Docker / Compose

```bash
docker compose up --build
```

The `docker-compose.yml` runs Qdrant on ports `6333`/`6334` and optionally the backend.

## AWS Deployment Notes

- Use Secrets Manager or Parameter Store for `JWT_SECRET`, `CLIENT_ID`, `CLIENT_SECRET`.
- Use RDS or managed PostgreSQL for production DB.
- Ensure the Qdrant service is reachable from the backend (use managed Qdrant Cloud or self-hosted on ECS).
- The `uploads/` directory should be on a persistent volume or object storage (S3) in production.
