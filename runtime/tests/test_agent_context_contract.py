from pathlib import Path


def test_agent_creation_requires_role_context_in_ui():
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

    assert "AGENT_CONTEXT_TEMPLATES" in dashboard
    assert "Agent context" in dashboard
    assert "setAgentContext" in dashboard
    assert "context: agentContext.trim()" in dashboard
    assert "Name, role, context, connection and model are required." in dashboard

    assert "Developer" in dashboard
    assert "Tester" in dashboard


def test_existing_agent_context_can_be_edited_from_command_core():
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
    api = (
        root
        / "apps"
        / "web"
        / "src"
        / "services"
        / "api.ts"
    ).read_text(encoding="utf-8")

    assert "AGENT CTX" in dashboard
    assert "openAgentContextDialog" in dashboard
    assert "saveAgentContext" in dashboard
    assert "api.updateAgent(agent.id" in dashboard
    assert 'context: string;' in api
    assert 'method: "PATCH"' in api


def test_agent_context_sqlite_migration_is_present():
    root = Path(__file__).resolve().parents[2]
    migrations = (
        root
        / "runtime"
        / "app"
        / "persistence"
        / "migrations.py"
    ).read_text(encoding="utf-8")

    assert 'if "context" not in columns:' in migrations
    assert "ALTER TABLE agents ADD COLUMN context TEXT" in migrations
