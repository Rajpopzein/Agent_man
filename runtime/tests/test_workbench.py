from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _project(tmp_path: Path):
    response = client.post(
        "/api/projects",
        json={
            "name": "Workbench Test",
            "workspace_path": str(tmp_path),
        },
    )
    assert response.status_code == 201
    return response.json()


def test_workbench_file_crud_download_and_export(tmp_path):
    project = _project(tmp_path)
    project_id = project["id"]

    created = client.put(
        f"/api/projects/{project_id}/files/content",
        json={"path": "src/app.py", "content": "print('hello')\n"},
    )
    assert created.status_code == 200

    listed = client.get(
        f"/api/projects/{project_id}/files",
        params={"path": "src"},
    )
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "app.py"

    read = client.get(
        f"/api/projects/{project_id}/files/content",
        params={"path": "src/app.py"},
    )
    assert read.status_code == 200
    assert "hello" in read.json()["content"]

    moved = client.post(
        f"/api/projects/{project_id}/files/move",
        json={
            "source": "src/app.py",
            "destination": "src/main.py",
        },
    )
    assert moved.status_code == 200

    downloaded = client.get(
        f"/api/projects/{project_id}/files/download",
        params={"path": "src/main.py"},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"print('hello')\n"

    exported = client.get(f"/api/projects/{project_id}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"

    deleted = client.delete(
        f"/api/projects/{project_id}/files",
        params={"path": "src/main.py"},
    )
    assert deleted.status_code == 200
    assert not (tmp_path / "src" / "main.py").exists()


def test_workbench_upload_is_project_scoped(tmp_path):
    project = _project(tmp_path)
    project_id = project["id"]

    uploaded = client.put(
        f"/api/projects/{project_id}/files/upload",
        params={"path": "assets/sample.bin"},
        content=b"\x00\x01\x02",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200
    assert (tmp_path / "assets" / "sample.bin").read_bytes() == b"\x00\x01\x02"

    blocked = client.put(
        f"/api/projects/{project_id}/files/content",
        json={"path": "../escape.txt", "content": "no"},
    )
    assert blocked.status_code == 400
