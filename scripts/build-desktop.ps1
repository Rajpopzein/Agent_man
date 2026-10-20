$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Require-Command([string]$Name, [string]$InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $InstallHint"
    }
}

Require-Command "python" "Install Python 3.12 and add it to PATH."
Require-Command "npm.cmd" "Install Node.js 22 or newer."
Require-Command "rustc" "Install Rust from rustup.rs and reopen PowerShell."
Require-Command "cargo" "Install Rust from rustup.rs and reopen PowerShell."

Write-Host "Installing Python runtime dependencies..."
python -m pip install -r .\runtime\requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

Write-Host "Building Agent Man runtime sidecar..."
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name agent-man-runtime --paths .\runtime --collect-all uvicorn --collect-all fastapi .\runtime\desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "Runtime sidecar build failed." }

$HostLine = rustc -vV | Select-String "^host:"
if (-not $HostLine) { throw "Unable to determine the Rust target triple." }
$HostTriple = ($HostLine.ToString() -replace "^host:\s*", "").Trim()

$BinaryDir = Join-Path $RepoRoot "apps\desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinaryDir | Out-Null
$SidecarTarget = Join-Path $BinaryDir ("agent-man-runtime-" + $HostTriple + ".exe")
Copy-Item ".\dist\agent-man-runtime.exe" $SidecarTarget -Force

Write-Host "Building React UI..."
npm.cmd --prefix .\apps\web install
if ($LASTEXITCODE -ne 0) { throw "Web dependency installation failed." }
Remove-Item Env:VITE_API_BASE -ErrorAction SilentlyContinue
npm.cmd --prefix .\apps\web run build
if ($LASTEXITCODE -ne 0) { throw "Web build failed." }

Write-Host "Building Windows desktop installer..."
npm.cmd --prefix .\apps\desktop install
if ($LASTEXITCODE -ne 0) { throw "Desktop dependency installation failed." }
npm.cmd --prefix .\apps\desktop run build
if ($LASTEXITCODE -ne 0) { throw "Tauri desktop build failed." }

$BundleDir = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release\bundle\nsis"
$Installer = Get-ChildItem $BundleDir -Filter "*.exe" | Select-Object -First 1
if (-not $Installer) { throw "Desktop build finished but no NSIS installer was found." }

Write-Host ""
Write-Host "Agent Man Windows installer:"
Write-Host $Installer.FullName
