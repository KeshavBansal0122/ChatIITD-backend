# Docker Setup Guide

This guide explains how to run the IIT Delhi Agentic Chatbot backend using Docker Compose.

## Prerequisites

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- Docker Compose (included with Docker Desktop)
- A Google API key for Gemini

## Important: Project Structure

This project expects the following files/directories to exist:
- `sources/` directory (contains JSONL files and programme structures) - should be in parent directory
- `courses.sqlite` file - should be in the current directory
- `snapshots/` directory (contains Qdrant snapshot files)

**Note:** The code uses relative paths (`../sources/`) which assumes these files are located relative to the working directory. Make sure these files exist before running Docker.

## Quick Start

### Option A: Using Startup Scripts (Recommended)

**For Windows (PowerShell):**
```powershell
.\start.ps1
```

**For Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

The startup scripts will:
1. Check for .env file and create it if missing
2. Validate GOOGLE_API_KEY is set
3. Start Qdrant
4. Restore snapshots automatically
5. Start all services

### Option B: Manual Setup

### 1. Configure Environment Variables

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your Google API key:
```
GOOGLE_API_KEY=your_actual_google_api_key_here
```

### 2. Restore Qdrant Snapshots (First Time Only)

Before starting the services for the first time, you need to restore the Qdrant vector database snapshots.

Start only Qdrant first:
```bash
docker-compose up -d qdrant
```

Wait for Qdrant to be ready (about 10 seconds), then restore snapshots:

```bash
# Restore rules snapshot
curl -X POST "http://localhost:6333/collections/rules/snapshots/upload?priority=snapshot" -H "Content-Type:application/octet-stream" --data-binary @snapshots/rules.snapshot

# Restore courses snapshot
curl -X POST "http://localhost:6333/collections/courses/snapshots/upload?priority=snapshot" -H "Content-Type:application/octet-stream" --data-binary @snapshots/courses.snapshot
```

**For PowerShell users**, use this format:
```powershell
# Restore rules snapshot
Invoke-RestMethod -Uri "http://localhost:6333/collections/rules/snapshots/upload?priority=snapshot" -Method POST -InFile "snapshots/rules.snapshot" -ContentType "application/octet-stream"

# Restore courses snapshot
Invoke-RestMethod -Uri "http://localhost:6333/collections/courses/snapshots/upload?priority=snapshot" -Method POST -InFile "snapshots/courses.snapshot" -ContentType "application/octet-stream"
```

### 3. Start All Services

```bash
docker-compose up -d
```

The backend will be available at: http://localhost:3000

### 4. Verify Services are Running

Check the status:
```bash
docker-compose ps
```

View logs:
```bash
# All services
docker-compose logs -f

# Just the backend
docker-compose logs -f backend

# Just Qdrant
docker-compose logs -f qdrant
```

## Services Overview

The Docker Compose setup includes:

1. **Qdrant** (Vector Database)
   - Port 6333: HTTP API
   - Port 6334: gRPC API
   - Data persisted in Docker volume: `qdrant_storage`
   - Snapshots mounted from `./snapshots`

2. **Backend** (FastAPI Application)
   - Port 3000: REST API
   - Dependencies: Qdrant, agent.py, tools.py
   - Persistent data: messages.db, sources/, snapshots/

## Common Commands

### Start services
```bash
docker-compose up -d
```

### Stop services
```bash
docker-compose down
```

### Restart services
```bash
docker-compose restart
```

### View logs
```bash
docker-compose logs -f
```

### Rebuild after code changes
```bash
docker-compose up -d --build
```

### Stop and remove everything (including volumes)
```bash
docker-compose down -v
```

## API Endpoints

Once running, you can access:

- **Health Check**: http://localhost:3000/health
- **API Documentation**: http://localhost:3000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

## Environment Variables

See `.env.example` for all available configuration options:

- `GOOGLE_API_KEY` - **Required**: Your Google API key for Gemini
- `DATABASE_URL` - Database connection string (default: sqlite:///messages.db)
- `JWT_SECRET` - Secret for JWT token signing
- `JWT_EXP_MINUTES` - JWT expiration time in minutes
- `GOOGLE_CLIENT_ID` - Google OAuth client ID for token validation

## Troubleshooting

### Backend fails to start

Check logs:
```bash
docker-compose logs backend
```

Common issues:
- Missing GOOGLE_API_KEY in .env file
- Qdrant not ready (wait a few seconds after starting)
- Missing required files (sources/, courses.sqlite, etc.)

### Qdrant collections not found

You need to restore the snapshots (see Step 2 in Quick Start)

### Port already in use

If ports 3000 or 6333 are already in use, modify the port mappings in `docker-compose.yml`:

```yaml
ports:
  - "YOUR_PORT:3000"  # Change YOUR_PORT to an available port
```

### Database persistence

The SQLite database `messages.db` is stored in the project directory and mounted into the container, so your data persists across container restarts.

For production, consider using PostgreSQL:
```env
DATABASE_URL=postgresql://user:password@db:5432/agentdb
```

## Development vs Production

### Development
- Uses SQLite for simplicity
- All services in one docker-compose.yml
- Code changes require rebuild: `docker-compose up -d --build`

### Production Recommendations
- Use managed PostgreSQL (AWS RDS, etc.)
- Use managed vector DB or persistent Qdrant deployment
- Set strong JWT_SECRET
- Use Docker secrets for sensitive data
- Deploy to ECS, EKS, or similar container orchestration platform
- Enable proper logging and monitoring

## Accessing the Container

To run commands inside the backend container:
```bash
docker-compose exec backend bash
```

## Stopping and Cleaning Up

### Stop services but keep data
```bash
docker-compose down
```

### Stop services and remove volumes (deletes Qdrant data)
```bash
docker-compose down -v
```

### Clean up Docker resources
```bash
# Remove unused images
docker image prune

# Remove all unused resources
docker system prune -a
```

## Notes

- The first run will download model weights for the reranker (~227MB)
- Qdrant data is persisted in a Docker volume
- Backend code changes require rebuilding the container
- For development, you may prefer running the backend locally and only Qdrant in Docker

## Support

For issues or questions, refer to the main project documentation or open an issue in the repository.
