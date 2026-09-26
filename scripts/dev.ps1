$ErrorActionPreference = "Stop"

$Root = Resolve-Path "$PSScriptRoot\.."
$RuntimePort = 8765
$ExpectedRevision = "audio-server-log-v1"
$RuntimePidFile = Join-Path $Root ".agent-man-runtime.pid"

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

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    # Reload workers can retain the socket after their parent has exited.
    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ParentProcessId -eq $ProcessId -and
                $_.Name -like "python*" -and
                $_.CommandLine -like "*multiprocessing.spawn*"
            } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        return
    }

    try {
        & taskkill /PID $ProcessId /T /F 2>$null | Out-Null
    }
    catch {
        try {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
        catch {
            # Best effort. Port verification below decides whether cleanup worked.
        }
    }
}

function Test-AgentManProcess {
    param([int]$ProcessId)

    $runtimePython = Join-Path $Root "runtime\.venv\Scripts\python.exe"
    $seen = @{}
    while ($ProcessId -gt 0 -and -not $seen.ContainsKey($ProcessId)) {
        $seen[$ProcessId] = $true
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if (-not $candidate) { return $false }
        if ($candidate.ExecutablePath -eq $runtimePython -and
            $candidate.CommandLine -match "uvicorn\s+app\.main:app" -and
            $candidate.CommandLine -match "--port\s+$RuntimePort(?:\s|$)") {
            return $true
        }
        $ProcessId = [int]$candidate.ParentProcessId
    }
    return $false
}

function Get-AgentManRuntimeProcesses {
    $portText = [string]$RuntimePort

    return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $command = [string]$_.CommandLine

            if ([string]::IsNullOrWhiteSpace($command)) {
                return $false
            }

            $looksLikeRuntime = (
                $command -match "uvicorn\s+app\.main:app" -or
                $command -match "python(?:\.exe)?\s+-m\s+uvicorn\s+app\.main:app"
            )

            $usesRuntimePort = (
                $command -match "--port\s+$portText(?:\s|$)" -or
                $command -match ":$portText(?:\s|$)"
            )

            return $looksLikeRuntime -and $usesRuntimePort -and (Test-AgentManProcess -ProcessId $_.ProcessId)
        }
}

function Stop-AgentManRuntime {
    Write-Host "Stopping existing Agent Man runtime on port $RuntimePort..." -ForegroundColor Yellow

    if (Test-Path $RuntimePidFile) {
        try {
            $storedPid = [int](Get-Content $RuntimePidFile -Raw).Trim()
            if ($storedPid -gt 0) {
                Stop-ProcessTree -ProcessId $storedPid
            }
        }
        catch {
            # Ignore stale/corrupt pid files and continue with process discovery.
        }
        finally {
            Remove-Item $RuntimePidFile -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($process in @(Get-AgentManRuntimeProcesses)) {
        Stop-ProcessTree -ProcessId ([int]$process.ProcessId)
    }

    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Milliseconds 350

        $listener = Get-AgentManListener
        if (-not $listener) {
            Write-Host "Port $RuntimePort is free." -ForegroundColor Green
            return
        }

        $health = Get-AgentManHealth
        if (-not ($health -and $health.runtime -eq "agent-man") -and
            -not (Test-AgentManProcess -ProcessId $listener.OwningProcess)) {
            throw "Port $RuntimePort is still in use by a non-Agent-Man process (PID $($listener.OwningProcess))."
        }

        Write-Host "Agent Man listener respawned on PID $($listener.OwningProcess); stopping it..." -ForegroundColor DarkYellow
        Stop-ProcessTree -ProcessId ([int]$listener.OwningProcess)

        foreach ($process in @(Get-AgentManRuntimeProcesses)) {
            Stop-ProcessTree -ProcessId ([int]$process.ProcessId)
        }
    }

    $listener = Get-AgentManListener
    if ($listener) {
        throw "Unable to stop the existing Agent Man runtime on port $RuntimePort. Remaining PID: $($listener.OwningProcess)."
    }
}

$listener = Get-AgentManListener
if ($listener) {
    $health = Get-AgentManHealth

    if (($health -and $health.runtime -eq "agent-man") -or
        (Test-AgentManProcess -ProcessId $listener.OwningProcess)) {
        Stop-AgentManRuntime
    }
    else {
        throw "Port $RuntimePort is already in use by another process (PID $($listener.OwningProcess)). Stop that process before starting Agent Man."
    }
}
elseif (Test-Path $RuntimePidFile) {
    try {
        $storedPid = [int](Get-Content $RuntimePidFile -Raw).Trim()
        if ($storedPid -gt 0) {
            Stop-ProcessTree -ProcessId $storedPid
        }
    }
    catch {
        # Ignore stale/corrupt pid files.
    }
    finally {
        Remove-Item $RuntimePidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Starting Agent Man runtime..." -ForegroundColor Cyan

$RuntimeCommand = @"
cd '$Root\runtime'
if (!(Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port $RuntimePort
"@

$startArgs = @{
    FilePath = "powershell"
    WindowStyle = "Hidden"
    ArgumentList = @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $RuntimeCommand)
    PassThru = $true
}
$runtimeHost = Start-Process @startArgs

Set-Content -Path $RuntimePidFile -Value $runtimeHost.Id -Encoding ascii

$healthy = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 250

    $health = Get-AgentManHealth
    if ($health -and $health.runtime -eq "agent-man") {
        if ($health.api_revision -ne $ExpectedRevision) {
            Stop-AgentManRuntime
            throw "Agent Man runtime started with stale API revision '$($health.api_revision)'. Expected '$ExpectedRevision'."
        }

        $healthy = $true
        break
    }

    if ($runtimeHost.HasExited) {
        Remove-Item $RuntimePidFile -Force -ErrorAction SilentlyContinue
        throw "Agent Man runtime host exited before the API became healthy."
    }
}

if (-not $healthy) {
    Stop-AgentManRuntime
    throw "Agent Man runtime did not become healthy on port $RuntimePort."
}

Write-Host "Agent Man runtime ready ($ExpectedRevision)." -ForegroundColor Green
Write-Host "Starting Agent Man UI..." -ForegroundColor Cyan

Set-Location "$Root\apps\web"
npm.cmd install
if ($LASTEXITCODE -ne 0) { throw "UI dependency installation failed. See the npm error above." }
npm.cmd run dev
