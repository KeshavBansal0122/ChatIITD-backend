# Backend API Schema

This document describes the HTTP API contract between the frontend and the backend.

Authentication:
- POST /auth/callback
  - Body: { "code": string, "state": string }
  - Response: { "access_token": string, "token_type": "bearer" }
  - Notes: OAuth callback endpoint for DevClub authentication. Frontend posts the authorization code and state received from DevClub OAuth to this endpoint.

Common headers:
- Authorization: Bearer <access_token>

Chats:
- GET /chats
  - Returns: [ { id, user_id, title, created_at } ]

- POST /chats
  - Body: { "title": string | null }
  - Returns: { id, user_id, title, created_at }

- POST /chats/new
  - Body: { "content": string }
  - Returns: { "chat": { id, user_id, title, created_at }, "message": { id, chat_id, sender, content, created_at }, "title": string }
  - Notes: Creates a new chat and sends the first message. Returns the chat, the assistant's response message, and the chat title.

- GET /chats/{chat_id}
  - Returns: { id, user_id, title, created_at }

- DELETE /chats/{chat_id}
  - Returns: 204 No Content
  - Notes: Deletes the chat and all associated messages.

Messages:
- GET /chats/{chat_id}/messages
  - Returns: [ { id, chat_id, sender, content, created_at } ]

- POST /chats/{chat_id}/messages
  - Body: { "content": string }
  - Returns: { id, chat_id, sender, content, created_at }
  - Notes: This endpoint forwards the content to the agent and stores both the user message and assistant response in the DB. The assistant response is returned in the body.

Error codes:
- 401 Unauthorized: missing/invalid token
- 404 Not Found: chat does not belong to user / missing chat
- 500 Server Error: invalid user id or internal error
