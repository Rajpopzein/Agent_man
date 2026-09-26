from app.tools.intelligence import plan_tools, recovery_guidance


def test_esp32_objective_builds_serial_tool_plan():
    allowed = {
        "list_serial_ports",
        "serial_open",
        "serial_read",
        "serial_write",
        "serial_close",
    }

    plan = plan_tools(
        "Access my ESP32 and read its serial output.",
        allowed,
    )

    assert plan.requires_tool is True
    assert plan.intent == "serial_hardware"
    assert plan.sequence[:3] == (
        "list_serial_ports",
        "serial_open",
        "serial_read",
    )
    assert plan.recommended_tools[:3] == (
        "list_serial_ports",
        "serial_open",
        "serial_read",
    )


def test_semantic_tool_matching_handles_unlisted_operational_request():
    allowed = {
        "list_processes",
        "read_process_output",
        "stop_process",
    }

    plan = plan_tools(
        "Inspect the managed process output for me.",
        allowed,
    )

    assert plan.requires_tool is True
    assert "read_process_output" in plan.recommended_tools


def test_serial_open_recovery_recommends_discovery():
    recovery = recovery_guidance(
        "serial_open",
        "Serial device is not currently enumerated: COM9",
        {"list_serial_ports", "serial_open"},
    )

    assert recovery == ("list_serial_ports",)
