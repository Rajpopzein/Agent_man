from pathlib import Path

import pytest

from app.core.permissions import ApprovalRequired
from app.sandbox.filesystem import ProjectFilesystem
from app.sandbox.processes import ProjectProcessRunner


def test_filesystem_stays_inside_workspace(tmp_path: Path):
    filesystem = ProjectFilesystem(str(tmp_path))
    filesystem.write_file("notes/test.txt", "hello")
    assert filesystem.read_file("notes/test.txt") == "hello"
    with pytest.raises(PermissionError):
        filesystem.read_file("../outside.txt")


def test_terminal_requires_explicit_approval(tmp_path: Path):
    runner = ProjectProcessRunner(str(tmp_path))
    with pytest.raises(ApprovalRequired):
        runner.run("echo blocked")
