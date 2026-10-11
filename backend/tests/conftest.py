import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh app with its own data directory (demo dataset loaded) for every test."""
    monkeypatch.setenv("SEVARO_DATA_DIR", str(tmp_path))
    for m in [m for m in list(sys.modules) if m == "main" or m.startswith("app")]:
        del sys.modules[m]
    import main  # noqa: F401
    from fastapi.testclient import TestClient
    with TestClient(importlib.import_module("main").app) as c:
        yield c


def demo_csv(name: str) -> bytes:
    return (ROOT / "data" / "demo" / f"{name}.csv").read_bytes()
