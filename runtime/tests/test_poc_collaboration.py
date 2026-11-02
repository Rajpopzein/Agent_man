"""POC contract tests: deliver messages without waiting for a shared turn loop."""
import time
from pathlib import Path

from app.api.poc_collaboration import CollaborationPOC


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("Timed out waiting for independently scheduled agents")


def test_agents_exchange_direct_messages(tmp_path: Path):
    poc = CollaborationPOC(tmp_path / "messages.sqlite3")
    try:
        poc.start()
        poc.post("user", "developer", "START DEMO: Login API")
        wait_until(lambda: len(poc.snapshot()["messages"]) == 3)
        snapshot = poc.snapshot()
        assert [(m["sender"], m["recipient"]) for m in snapshot["messages"]] == [
            ("user", "developer"),
            ("developer", "tester"),
            ("tester", "developer"),
        ]
        wait_until(lambda: all(m["status"] == "processed" for m in poc.snapshot()["messages"]))
        assert "Tester feedback" in next(a["latest"] for a in poc.snapshot()["agents"] if a["agent"] == "developer")
        assert all(poc.snapshot()["running"].values())
    finally:
        poc.stop()


def test_user_can_message_tester_without_waiting_for_developer(tmp_path: Path):
    poc = CollaborationPOC(tmp_path / "messages.sqlite3")
    try:
        poc.start()
        direct = poc.post("user", "tester", "What is your status?")
        wait_until(lambda: poc.snapshot()["messages"][0]["status"] == "processed")
        assert poc.snapshot()["messages"][0]["id"] == direct
        assert "What is your status?" in next(a["latest"] for a in poc.snapshot()["agents"] if a["agent"] == "tester")
    finally:
        poc.stop()


def test_queued_messages_survive_restart(tmp_path: Path):
    path = tmp_path / "messages.sqlite3"
    first = CollaborationPOC(path)
    message_id = first.post("user", "tester", "Persistent message")
    second = CollaborationPOC(path)
    try:
        second.start()
        wait_until(lambda: second.snapshot()["messages"][0]["status"] == "processed")
        assert second.snapshot()["messages"][0]["id"] == message_id
    finally:
        second.stop()
