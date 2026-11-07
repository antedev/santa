$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\pip install -r requirements.txt
}
Write-Host "Startar Julklappsspelet på http://localhost:8080 ..." -ForegroundColor Green
.\.venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
