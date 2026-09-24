$ErrorActionPreference="Stop"
Write-Host "Starting Agent Man runtime..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$PSScriptRoot\..\backend'; if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; uvicorn app.main:app --reload --port 8765"
Write-Host "Starting Agent Man UI..." -ForegroundColor Cyan
Set-Location "$PSScriptRoot\..\frontend"
npm install
npm run dev
