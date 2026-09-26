from pathlib import Path


def test_dashboard_presents_assigned_worker_as_connecting():
    root = Path(__file__).resolve().parents[2]
    dashboard = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "dashboard"
        / "Dashboard.tsx"
    ).read_text(encoding="utf-8")

    assert 'activeWorker?.state === "assigned"' in dashboard
    assert '"CONNECTING"' in dashboard
    assert '"Connecting with " + activeWorker.name + "..."' in dashboard
    assert 'item.state === "assigned"' in dashboard
    assert '? "connecting"' in dashboard
