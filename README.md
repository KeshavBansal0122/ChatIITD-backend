# chatiitd-rag

## Docker setup
- Create a `.env` file in the project root with the required keys. At minimum:
  - `GOOGLE_API_KEY` for Gemini access
  - `QDRANT_URL` (defaults to `http://qdrant:6333` in Docker Compose)
- Build and start the stack with `docker compose up --build`.
- The FastAPI backend will be reachable at `http://localhost:3000`.
- Qdrant runs in the companion container at `http://localhost:6333` (`/dashboard` for the UI).
- Persistent volumes keep the FastAPI SQLite data (`backend-data`) and Qdrant collections (`qdrant-storage`).

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