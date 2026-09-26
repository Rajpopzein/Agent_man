from pathlib import Path

from app.events.bus import EventBus
from app.main import app


def test_event_bus_filters_project_updates_without_polling():
    bus = EventBus(max_events=20)
    cursor = bus.current_sequence()

    bus.emit(
        "agent.state.changed",
        project_id="project-a",
        agent_id="agent-a",
        state="working",
    )
    bus.emit(
        "agent.state.changed",
        project_id="project-b",
        agent_id="agent-b",
        state="validating",
    )

    next_cursor, events = bus.wait_since(
        cursor,
        timeout=0,
        project_id="project-a",
    )

    assert next_cursor == 2
    assert len(events) == 1
    assert events[0]["project_id"] == "project-a"
    assert events[0]["agent_id"] == "agent-a"
    assert events[0]["state"] == "working"


def test_event_stream_route_is_registered():
    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }
    assert "/api/events/stream" in paths


def test_dashboard_does_not_poll_agents_while_executive_is_busy():
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

    assert "new EventSource(" in dashboard
    assert "api.runtimeEventsUrl(project.id)" in dashboard

    old_polling = """if (!busy || !project) return;

    void refreshWorkers(project.id);
    const timer = window.setInterval(() => {
      void refreshWorkers(project.id);
    }, 650);"""
    assert old_polling not in dashboard

    # One final refresh after the Executive request is expected.
    assert dashboard.count("await refreshWorkers(project.id);") == 1
