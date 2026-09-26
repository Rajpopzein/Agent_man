$ErrorActionPreference="Stop"
$Root=Resolve-Path "$PSScriptRoot\.."
$RuntimePort=8765
$ExpectedRevision="executive-tools-v2"

function Get-AgentManListener {
    return Get-NetTCPConnection -LocalPort $RuntimePort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-AgentManHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/health" -TimeoutSec 2
    }
    catch {
        return $null
    }
}

$listener=Get-AgentManListener
if ($listener) {
    $health=Get-AgentManHealth
    if ($health -and $health.runtime -eq "agent-man") {
        Write-Host "Stopping existing Agent Man runtime on port $RuntimePort..." -ForegroundColor Yellow
        foreach ($runtimeListener in @(Get-NetTCPConnection -LocalPort $RuntimePort -State Listen -ErrorAction SilentlyContinue)) {
            if (Get-Process -Id $runtimeListener.OwningProcess -ErrorAction SilentlyContinue) {
                & taskkill /PID $runtimeListener.OwningProcess /T /F | Out-Null
            }

            # Windows can retain the listener's original PID after a reload worker
            # inherits its socket and the parent exits. Stop those orphan workers.
            if (-not (Get-Process -Id $runtimeListener.OwningProcess -ErrorAction SilentlyContinue)) {
                Get-CimInstance Win32_Process |
                    Where-Object {
                        $_.ParentProcessId -eq $runtimeListener.OwningProcess -and
                        $_.Name -like "python*" -and
                        $_.CommandLine -like "*multiprocessing.spawn*"
                    } |
                    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
        }

        for ($i=0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-AgentManListener)) {
                break
            }
        }

        if (Get-AgentManListener) {
            throw "Unable to stop the existing Agent Man runtime on port $RuntimePort."
        }
    }
    else {
        throw "Port $RuntimePort is already in use by another process. Stop that process before starting Agent Man."
    }
}

Write-Host "Starting Agent Man runtime..." -ForegroundColor Cyan
$RuntimeCommand=@"
cd '$Root\runtime'
if (!(Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port $RuntimePort
"@
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-Command",$RuntimeCommand

$healthy=$false
for ($i=0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 250
    $health=Get-AgentManHealth
    if ($health -and $health.runtime -eq "agent-man") {
        if ($health.api_revision -ne $ExpectedRevision) {
            throw "Agent Man runtime started with stale API revision '$($health.api_revision)'. Expected '$ExpectedRevision'."
        }
        $healthy=$true
        break
    }
}

if (-not $healthy) {
    throw "Agent Man runtime did not become healthy on port $RuntimePort."
}

Write-Host "Agent Man runtime ready ($ExpectedRevision)." -ForegroundColor Green
Write-Host "Starting Agent Man UI..." -ForegroundColor Cyan
Set-Location "$Root\apps\web"
npm.cmd install
if ($LASTEXITCODE -ne 0) { throw "UI dependency installation failed. See the npm error above." }
npm.cmd run dev
