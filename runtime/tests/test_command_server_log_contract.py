from pathlib import Path


def test_command_core_places_ai_server_log_beside_directive():
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
    css = (
        root
        / "apps"
        / "web"
        / "src"
        / "styles"
        / "global.css"
    ).read_text(encoding="utf-8")

    assert 'className="directiveWorkspace"' in dashboard
    assert 'className="directiveMain"' in dashboard
    assert 'className="aiServerLogPanel"' in dashboard
    assert "AI SERVER / LIVE" in dashboard
    assert "Model Traffic" in dashboard
    assert "Open full LLM logs" in dashboard

    assert "liveModelCalls" in dashboard
    assert "api.llmLogs(currentProject.id, 12)" in dashboard
    assert "await refreshServerLogs(project.id);" in dashboard

    assert ".directiveWorkspace" in css
    assert "grid-template-columns:minmax(0,1fr) 320px" in css
    assert ".aiServerLogPanel" in css


def test_ai_server_log_uses_existing_event_stream_not_polling():
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

    assert 'runtimeEvent.type.startsWith("agent.response.")' in dashboard
    assert "runtimeEvent.provider_id" in dashboard
    assert "runtimeEvent.model" in dashboard
    assert "runtimeEvent.duration_ms" in dashboard

    assert "setInterval(() => {\n      void refreshServerLogs" not in dashboard
