from pathlib import Path


def test_dev_launcher_guards_against_stale_uvicorn_reload_runtime():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "dev.ps1").read_text(encoding="utf-8")

    assert '.agent-man-runtime.pid' in script
    assert 'Get-CimInstance Win32_Process' in script
    assert 'uvicorn\\s+app\\.main:app' in script
    assert 'taskkill /PID $ProcessId /T /F' in script
    assert 'Agent Man listener respawned' in script
    assert 'Remaining PID:' in script
    assert 'api_revision -ne $ExpectedRevision' in script
    assert 'Start-Process @startArgs' in script
    assert 'PassThru = $true' in script
