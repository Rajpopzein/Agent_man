from pathlib import Path


def test_mission_control_uses_executive_effective_access():
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

    assert "EffectiveToolAccess" in dashboard
    assert "setExecutiveAccess" in dashboard
    assert "api.effectiveMainAgentTools" in dashboard

    assert (
        "const activeTools = executiveAccess?.count ?? 0;"
        in dashboard
    )
    assert "EXECUTIVE TOOLS" in dashboard
    assert "SAFE AUTO TOOLS" in dashboard

    assert 'tool.approval_gate === "exec"' in dashboard
    assert 'tool.approval_gate === "net"' in dashboard
    assert 'tool.approval_gate === "hw"' in dashboard
    assert 'tool.approval_gate === "delete"' in dashboard

    assert "Tool assignment controls what Agent Man can see." in dashboard
    assert "Run approval arms risky actions for this mission." in dashboard

    # Returning from Settings/Tools to Command Core refreshes the
    # authoritative runtime access instead of using stale local data.
    assert 'if (view === "dashboard" && project?.id)' in dashboard
    assert "void refreshExecutiveAccess(project.id);" in dashboard


def test_mission_control_does_not_count_global_tools_as_executive_tools():
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

    assert (
        "const activeTools = tools.filter((tool) => tool.enabled).length;"
        not in dashboard
    )
