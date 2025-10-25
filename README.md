# chatiitd-rag

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
1) Run qdrant using docker:
```
sudo docker run -d -p 6333:6333 -p 6334:6334 --restart unless-stopped qdrant/qdrant
```

2) Go to http://localhost:6333/dashboard and upload the 2 snapshots from https://drive.google.com/drive/folders/17WIUqR5XkIPWMJ-Gsb_P-yfqFgu4QXQj?usp=sharing

3) Create a .env file in the root directory with the following content:
```
GOOGLE_API_KEY="Gemini api key"
QDRANT_URL="http://localhost:6333"
```

4) Install dependencies and run uvicorn from the project root:
```
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 3000
``` 