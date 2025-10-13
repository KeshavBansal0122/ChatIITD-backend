# Docker Setup - Changes Summary

## Files Created

### 1. `Dockerfile`
- Base image: Python 3.11-slim
- Installs system dependencies (gcc, g++, git)
- Installs Python packages from backend/requirements.txt
- Copies entire application
- Exposes port 3000
- Runs uvicorn server on 0.0.0.0:3000

### 2. `docker-compose.yml`
Two services:
- **qdrant**: Qdrant vector database
  - Ports: 6333 (HTTP), 6334 (gRPC)
  - Persistent volume for data storage
  - Mounts snapshots directory
  
- **backend**: FastAPI application
  - Port: 3000
  - Environment variables for configuration
  - Connects to Qdrant service
  - Mounts volumes for persistence (database, sources, snapshots)
  - Health check on startup

### 3. `.env.example`
Template for environment variables:
- GOOGLE_API_KEY (required)
- QDRANT_URL
- DATABASE_URL
- JWT_SECRET
- JWT_EXP_MINUTES
- GOOGLE_CLIENT_ID

### 4. `.dockerignore`
Excludes from Docker build:
- Python cache files
- Virtual environments
- IDE files
- .env files (use .env.example as template)
- Git files
- Test files
- Build artifacts

### 5. `DOCKER_README.md`
Comprehensive documentation including:
- Prerequisites
- Quick start guide (automated with scripts and manual)
- Services overview
- Common commands
- API endpoints
- Environment variables reference
- Troubleshooting guide
- Development vs Production notes

### 6. `start.sh` (Linux/Mac)
Automated startup script that:
- Checks for .env file
- Validates GOOGLE_API_KEY
- Starts Qdrant first
- Waits for Qdrant to be ready
- Restores snapshots
- Starts all services
- Displays service URLs

### 7. `start.ps1` (Windows PowerShell)
Windows version of the startup script with same functionality

## Files Modified

### 1. `agent.py`
**Change:** Made Qdrant URL configurable via environment variable
```python
# Before:
client = qdrant_client.QdrantClient(url="http://localhost:6333")

# After:
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
client = qdrant_client.QdrantClient(url=QDRANT_URL)
```

**Reason:** Allows the backend to connect to Qdrant container using the service name (`http://qdrant:6333`) in Docker while still working locally.

## How It Works

### Architecture
```
┌─────────────────┐
│   User/Client   │
└────────┬────────┘
         │ HTTP :3000
         ▼
┌─────────────────┐
│  Backend (API)  │
│  - FastAPI      │
│  - Agent        │
│  - Tools        │
└────┬────────┬───┘
     │        │
     │        │ HTTP :6333
     │        ▼
     │   ┌──────────┐
     │   │  Qdrant  │
     │   │ (Vector  │
     │   │   DB)    │
     │   └──────────┘
     │
     ▼
┌──────────┐
│ SQLite   │
│messages  │
│   .db    │
└──────────┘
```

### Network
- Both services run on a custom bridge network: `chatbot-network`
- Backend connects to Qdrant using the service name as hostname
- Ports exposed to host: 3000 (backend), 6333/6334 (Qdrant)

### Data Persistence
1. **Qdrant data**: Stored in Docker volume `qdrant_storage`
2. **Messages database**: SQLite file mounted from host
3. **Snapshots**: Directory mounted from host for easy restoration
4. **Sources**: Directory mounted from host (required for tools.py)

## Usage

### Starting Services
```bash
# Automated (recommended)
.\start.ps1  # Windows
./start.sh   # Linux/Mac

# Manual
docker-compose up -d
```

### Stopping Services
```bash
docker-compose down
```

### Viewing Logs
```bash
docker-compose logs -f backend
```

### Rebuilding After Code Changes
```bash
docker-compose up -d --build
```

## Environment Variables in Docker

The docker-compose.yml sets:
- `QDRANT_URL=http://qdrant:6333` (uses Docker service name)
- All other variables from .env file or defaults

## Prerequisites for Running

1. **Required Files/Directories:**
   - `sources/` directory with JSONL files (in parent directory, accessible via `../sources/`)
   - `courses.sqlite` database file
   - `snapshots/rules.snapshot`
   - `snapshots/courses.snapshot`
   - `.env` file with GOOGLE_API_KEY

2. **Software:**
   - Docker Desktop (Windows/Mac) or Docker Engine (Linux)
   - Docker Compose

## Testing the Setup

1. Check health: `curl http://localhost:3000/health`
2. View API docs: http://localhost:3000/docs
3. Check Qdrant: http://localhost:6333/dashboard

## Differences from Manual Setup

| Aspect | Manual | Docker |
|--------|--------|--------|
| Qdrant | Run separately with docker run | Managed by docker-compose |
| Backend | uvicorn command | Container with uvicorn |
| Dependencies | Local venv | Container image |
| Networking | localhost everywhere | Service names in compose |
| Data | Local files | Mounted volumes |

## Known Considerations

1. **Relative Paths**: The code uses `../sources/` which assumes specific directory structure
2. **First Run**: Requires snapshot restoration (automated in scripts)
3. **Model Downloads**: First run downloads HuggingFace model (~227MB)
4. **Platform**: Docker commands work on Windows, Linux, and Mac

## Future Improvements

1. Use PostgreSQL instead of SQLite for production
2. Add health checks in docker-compose
3. Multi-stage Docker build for smaller image
4. Separate dev and prod compose files
5. Add CI/CD pipeline configurations
