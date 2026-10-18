$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Python = Join-Path $Root "runtime\.venv\Scripts\python.exe"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path $Python)) {
    Invoke-Checked "python" @("-m", "venv", "$Root\runtime\.venv")
}
Invoke-Checked $Python @("-m", "pip", "install", "-r", "$Root\runtime\requirements.txt", "-r", "$Root\apps\desktop\requirements-build.txt")
$WebBuild = Join-Path $Root "apps\desktop\build\web"
New-Item -ItemType Directory -Path $WebBuild -Force | Out-Null
Copy-Item -Path "$Root\apps\web\package.json", "$Root\apps\web\package-lock.json", "$Root\apps\web\tsconfig.json", "$Root\apps\web\index.html" -Destination $WebBuild -Force
if (Test-Path "$WebBuild\src") {
    $SourceCopy = (Resolve-Path "$WebBuild\src").Path
    if ($SourceCopy -ne "$Root\apps\desktop\build\web\src") { throw "Unexpected build source path" }
    Remove-Item -LiteralPath $SourceCopy -Recurse -Force
}
Copy-Item -LiteralPath "$Root\apps\web\src" -Destination $WebBuild -Recurse
Push-Location $WebBuild
try {
    Invoke-Checked "npm.cmd" @("ci")
    Invoke-Checked "npm.cmd" @("run", "build")
}
finally { Pop-Location }

Invoke-Checked $Python @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--name", "AgentMan", "--paths", "$Root\runtime",
    "--add-data", "$WebBuild\dist;web",
    "--collect-submodules", "uvicorn", "--collect-submodules", "app",
    "--distpath", "$Root\dist", "--workpath", "$Root\apps\desktop\build",
    "--specpath", "$Root\apps\desktop", "$Root\apps\desktop\launcher.py"
)
Write-Host "Executable: $Root\dist\AgentMan.exe" -ForegroundColor Green
