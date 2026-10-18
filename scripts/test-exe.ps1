$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$LogDir = Join-Path $Root "apps\desktop\build"
$OutputLog = Join-Path $LogDir "smoke-stdout.log"
$ErrorLog = Join-Path $LogDir "smoke-stderr.log"
$AppProcess = Start-Process -FilePath "$Root\dist\AgentMan.exe" -ArgumentList "--no-browser" -WorkingDirectory $env:TEMP -WindowStyle Hidden -PassThru -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog
try {
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 90; $Attempt++) {
        if ($AppProcess.HasExited) { throw "EXE exited: $(Get-Content $ErrorLog -Raw)" }
        $LogText = Get-Content $OutputLog -Raw -ErrorAction SilentlyContinue
        if ($LogText -match 'Agent Man: (http://127\.0\.0\.1:\d+)') {
            $BaseUrl = $Matches[1]
            try {
                $Health = Invoke-RestMethod "$BaseUrl/health" -TimeoutSec 2
                if ($Health.runtime -eq "agent-man") { $Ready = $true; break }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) { throw "EXE did not become healthy: $(Get-Content $ErrorLog -Raw)" }
    $Page = Invoke-WebRequest "$BaseUrl/" -UseBasicParsing
    if ($Page.Content -notmatch 'src="([^"]+\.js)"') { throw "Missing UI bundle" }
    $AssetUrl = $Matches[1]
    $Asset = Invoke-WebRequest "$BaseUrl$AssetUrl" -UseBasicParsing
    if ($Asset.StatusCode -ne 200) { throw "UI bundle failed" }
    $Projects = Invoke-WebRequest "$BaseUrl/api/projects" -UseBasicParsing
    if ($Projects.StatusCode -ne 200) { throw "Projects API failed" }
    Write-Host "PASS: packaged EXE health, UI, JavaScript asset and projects API at $BaseUrl"
}
finally {
    if (-not $AppProcess.HasExited) { & taskkill /PID $AppProcess.Id /T /F | Out-Null }
}
