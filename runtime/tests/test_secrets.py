import os

import pytest
from cryptography.fernet import Fernet

from app.core.secrets import SecretStore


@pytest.mark.skipif(os.name == "nt", reason="Linux secret-vault behavior")
def test_non_windows_secret_store_encrypts_and_reads(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("AGENT_MAN_SECRET_KEY", key)
    store = SecretStore(tmp_path)

    store.set("gemini:test", "super-secret-api-key")

    raw = next(tmp_path.glob("*.secret")).read_text(encoding="ascii")
    assert "super-secret-api-key" not in raw
    assert store.exists("gemini:test") is True
    assert store.get("gemini:test") == "super-secret-api-key"


@pytest.mark.skipif(os.name == "nt", reason="Linux secret-vault behavior")
def test_non_windows_secret_store_requires_master_key(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_MAN_SECRET_KEY", raising=False)
    store = SecretStore(tmp_path)

    with pytest.raises(RuntimeError, match="AGENT_MAN_SECRET_KEY"):
        store.set("gemini:test", "value")
