# Agentic Chatbot Backend

This FastAPI backend provides REST endpoints for authentication (OIDC id_token exchange), chat management, storing messages, and invoking the existing chatbot agent.

Quick start (local):

- Create a virtualenv and install requirements

```pwsh
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- Run the backend

```pwsh
cd agentic_chatbot/backend
uvicorn agentic_chatbot.backend.main:app --reload
```

Environment variables:
- JWT_SECRET: secret for signing access tokens (change in production)
- JWT_EXP_MINUTES: expiration minutes for JWTs
- DATABASE_URL: SQLModel/SQLAlchemy database URL. Defaults to sqlite:///messages.db for local dev. Example Postgres: postgresql://user:pass@db:5432/agentdb
- GOOGLE_CLIENT_ID: (optional) Google OAuth client ID used to validate id_token audience

Auth flow (recommended):
- Frontend performs OAuth with Google (or other provider) and obtains an id_token.
- Frontend POSTs the id_token to /auth/login. The backend validates the id_token and returns a signed JWT for session use.

API schema (summary):
- POST /auth/login { id_token } -> { access_token }
- GET /chats -> list user chats (requires Bearer JWT)
- POST /chats { title } -> create chat
- GET /chats/{chat_id} -> get chat
- POST /chats/{chat_id}/messages { content } -> send message to agent (stores message and assistant response)
- GET /chats/{chat_id}/messages -> list messages

Docker / Compose:
- Build with `docker compose up --build` from the `agentic_chatbot/backend` directory.

AWS Deployment notes:
- Use Secrets Manager or Parameter Store for JWT_SECRET and other secrets.
- Use RDS or managed PostgreSQL for production DB (update SQLModel DATABASE_URL accordingly).
- When containerizing: mount a volume or use a managed DB so both the backend and the agent can access the same persistent datastore.
- Use ECS/Fargate or EKS for container orchestration. Ensure the Qdrant service (or managed vector DB) is reachable from the backend.
