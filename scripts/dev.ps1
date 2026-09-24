$ErrorActionPreference="Stop"
$Root=Resolve-Path "$PSScriptRoot\.."
Write-Host "Starting Agent Man runtime..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$Root\runtime'; if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; uvicorn app.main:app --reload --port 8765"
Write-Host "Starting Agent Man UI..." -ForegroundColor Cyan
Set-Location "$Root\apps\web"
npm install
npm run dev
