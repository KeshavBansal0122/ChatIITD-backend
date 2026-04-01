# chatiitd-rag

## API Documentation

The backend now includes comprehensive Swagger/OpenAPI documentation with interactive testing capabilities:

### Available Documentation Endpoints

- **Swagger UI (Default)**: `http://localhost:3000/docs`
  - Standard Swagger interface for API exploration and testing
  
- **Swagger UI (Enhanced)**: `http://localhost:3000/docs-advanced`
  - Enhanced interface with additional features:
    - Persistent authorization (stays logged in)
    - Deep linking support
    - Extended model details
    - Better testing capabilities

- **ReDoc**: `http://localhost:3000/redoc`
  - Alternative documentation format with clean, responsive design
  - Great for reading API documentation

- **OpenAPI Schema**: `http://localhost:3000/openapi.json`
  - Raw OpenAPI 3.0 specification in JSON format

### Authentication with DevClub OAuth

The API uses DevClub OAuth (https://oauth.devclub.in/) for authentication:

1. **Setup**: Register your application at https://oauth.devclub.in/
   - Get your `client_id` and `client_secret`
   - Configure your redirect URIs

2. **Integration Flow**:
   ```
   GET /auth/signin-url?redirect_uri=<your_callback_url>
   → Returns DevClub OAuth signin URL
   → Redirect user to OAuth signin URL  
   → User authenticates with DevClub
   → DevClub redirects back with code & state
   → POST /auth/callback with {code, state}
   → Returns JWT access_token
   ```

3. **Using the API Documentation**:
   - The enhanced docs provide a complete authentication flow example
   - Click "Authorize" in Swagger UI and enter `Bearer <your-jwt-token>`
   - Your token will be included in all subsequent requests

4. **API Categories**:
   - **System**: Health checks and status endpoints
   - **Authentication**: DevClub OAuth integration endpoints
   - **Chat Management**: Create and manage chat sessions  
   - **Messages**: Send messages and retrieve conversation history
   - **Admin - Document Management**: Upload, process, and manage PDF documents (Admin only)

## Environment Configuration

Create a `.env` file with the following variables:

```bash
# Google API Key for Gemini LLM (REQUIRED)
GOOGLE_API_KEY=your_google_api_key_here

# DevClub OAuth Configuration (REQUIRED)
CLIENT_ID=your_devclub_client_id_here
CLIENT_SECRET=your_devclub_client_secret_here

# JWT Secret (IMPORTANT: Change in production!)
JWT_SECRET=change-me-in-prod

# Optional configurations
QDRANT_URL=http://localhost:6333
DATABASE_URL=sqlite:///messages.db
JWT_EXP_MINUTES=1440
DEMO_MODE=false
```

## Docker setup

- Create a `.env` file in the project root with the required keys. At minimum:
  - `GOOGLE_API_KEY` for Gemini access
- `docker compose` now starts both the FastAPI backend and a Qdrant instance.
- Place any Qdrant snapshot files inside the top-level `snapshots/` directory before you bring the stack up. They are mounted at `/qdrant/snapshots` in the container for restore operations.
- Build and start the stack with `docker compose up --build`.
- The FastAPI backend will be reachable at `http://localhost:3000`.
- Qdrant will expose its API at `http://localhost:6333` (dashboard on `/dashboard`).
- Persistent volumes keep the backend SQLite data (`backend-data`) and the qdrant collection storage (`qdrant-storage`).

## Manual run (without Docker)

1. Run qdrant using docker:

```
sudo docker run -d -p 6333:6333 -p 6334:6334 --restart unless-stopped qdrant/qdrant
```

2. Go to http://localhost:6333/dashboard and upload the 2 snapshots from snapshots/

3. Create a .env file in the root directory with the following content:

```
GOOGLE_API_KEY="Gemini api key"
QDRANT_URL="http://localhost:6333"
```

4. Install dependencies and run uvicorn from the project root:

```
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 3000
```
