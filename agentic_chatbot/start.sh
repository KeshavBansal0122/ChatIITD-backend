#!/bin/bash
# Startup script for the chatbot backend with Docker

set -e

echo "==================================="
echo "IIT Delhi Chatbot Docker Startup"
echo "==================================="

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "✅ Please edit .env and add your GOOGLE_API_KEY before continuing."
    exit 1
fi

# Check if GOOGLE_API_KEY is set
if ! grep -q "GOOGLE_API_KEY=.*[^_].*" .env; then
    echo "❌ Error: GOOGLE_API_KEY not set in .env file"
    echo "Please edit .env and add your Google API key."
    exit 1
fi

echo "✅ Environment configuration found"

# Start Qdrant first
echo ""
echo "Starting Qdrant vector database..."
docker-compose up -d qdrant

# Wait for Qdrant to be ready
echo "Waiting for Qdrant to be ready..."
sleep 10

# Check if snapshots exist
if [ ! -f snapshots/rules.snapshot ] || [ ! -f snapshots/courses.snapshot ]; then
    echo "⚠️  Warning: Snapshot files not found in snapshots/ directory"
    echo "Please ensure rules.snapshot and courses.snapshot exist."
else
    echo ""
    echo "Restoring Qdrant snapshots..."
    
    # Restore rules snapshot
    echo "Restoring rules collection..."
    curl -X POST "http://localhost:6333/collections/rules/snapshots/upload?priority=snapshot" \
         -H "Content-Type:application/octet-stream" \
         --data-binary @snapshots/rules.snapshot
    
    # Restore courses snapshot
    echo ""
    echo "Restoring courses collection..."
    curl -X POST "http://localhost:6333/collections/courses/snapshots/upload?priority=snapshot" \
         -H "Content-Type:application/octet-stream" \
         --data-binary @snapshots/courses.snapshot
    
    echo "✅ Snapshots restored successfully"
fi

# Start all services
echo ""
echo "Starting all services..."
docker-compose up -d

echo ""
echo "==================================="
echo "✅ All services started successfully!"
echo "==================================="
echo ""
echo "Backend API: http://localhost:3000"
echo "API Docs: http://localhost:3000/docs"
echo "Qdrant Dashboard: http://localhost:6333/dashboard"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
echo "==================================="
