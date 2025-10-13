# PowerShell startup script for the chatbot backend with Docker

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "IIT Delhi Chatbot Docker Startup" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "⚠️  Warning: .env file not found!" -ForegroundColor Yellow
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "✅ Please edit .env and add your GOOGLE_API_KEY before continuing." -ForegroundColor Green
    exit 1
}

# Check if GOOGLE_API_KEY is set
$envContent = Get-Content .env -Raw
if ($envContent -notmatch "GOOGLE_API_KEY=.+") {
    Write-Host "❌ Error: GOOGLE_API_KEY not set in .env file" -ForegroundColor Red
    Write-Host "Please edit .env and add your Google API key." -ForegroundColor Red
    exit 1
}

Write-Host "✅ Environment configuration found" -ForegroundColor Green

# Start Qdrant first
Write-Host ""
Write-Host "Starting Qdrant vector database..." -ForegroundColor Cyan
docker-compose up -d qdrant

# Wait for Qdrant to be ready
Write-Host "Waiting for Qdrant to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Check if snapshots exist
if (-not (Test-Path snapshots/rules.snapshot) -or -not (Test-Path snapshots/courses.snapshot)) {
    Write-Host "⚠️  Warning: Snapshot files not found in snapshots/ directory" -ForegroundColor Yellow
    Write-Host "Please ensure rules.snapshot and courses.snapshot exist." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Restoring Qdrant snapshots..." -ForegroundColor Cyan
    
    # Restore rules snapshot
    Write-Host "Restoring rules collection..." -ForegroundColor Yellow
    try {
        Invoke-RestMethod -Uri "http://localhost:6333/collections/rules/snapshots/upload?priority=snapshot" `
                          -Method POST `
                          -InFile "snapshots/rules.snapshot" `
                          -ContentType "application/octet-stream" | Out-Null
        Write-Host "✅ Rules collection restored" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Warning: Failed to restore rules collection: $_" -ForegroundColor Yellow
    }
    
    # Restore courses snapshot
    Write-Host "Restoring courses collection..." -ForegroundColor Yellow
    try {
        Invoke-RestMethod -Uri "http://localhost:6333/collections/courses/snapshots/upload?priority=snapshot" `
                          -Method POST `
                          -InFile "snapshots/courses.snapshot" `
                          -ContentType "application/octet-stream" | Out-Null
        Write-Host "✅ Courses collection restored" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Warning: Failed to restore courses collection: $_" -ForegroundColor Yellow
    }
}

# Start all services
Write-Host ""
Write-Host "Starting all services..." -ForegroundColor Cyan
docker-compose up -d

Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host "✅ All services started successfully!" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend API: " -NoNewline
Write-Host "http://localhost:3000" -ForegroundColor Blue
Write-Host "API Docs: " -NoNewline
Write-Host "http://localhost:3000/docs" -ForegroundColor Blue
Write-Host "Qdrant Dashboard: " -NoNewline
Write-Host "http://localhost:6333/dashboard" -ForegroundColor Blue
Write-Host ""
Write-Host "To view logs: " -NoNewline
Write-Host "docker-compose logs -f" -ForegroundColor Yellow
Write-Host "To stop: " -NoNewline
Write-Host "docker-compose down" -ForegroundColor Yellow
Write-Host "===================================" -ForegroundColor Cyan
