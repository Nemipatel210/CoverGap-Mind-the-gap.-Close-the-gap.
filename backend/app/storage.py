"""File-based persistence with atomic writes (write temp file, fsync, os.replace)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from .config import ACTIVE_DIR, DEMO_DIR, STAGING_DIR, STATE_DIR

LOCK = threading.RLock()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(name: str, default: Any) -> Any:
    path = STATE_DIR / name
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def write_json(name: str, data: Any) -> None:
    atomic_write_text(STATE_DIR / name, json.dumps(data, indent=2, default=str))


def ensure_dirs() -> None:
    for d in (ACTIVE_DIR, STAGING_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not any(ACTIVE_DIR.glob("*.csv")):
        copy_demo_to_active()


def copy_demo_to_active() -> None:
    tmp = ACTIVE_DIR.parent / ".active_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(DEMO_DIR, tmp)
    (tmp / "manifest.json").write_text(json.dumps({"label": "Sevaro synthetic demo (Tue 17 Mar 2026)", "source": "demo"}))
    swap_active(tmp)


def swap_active(new_dir: Path) -> None:
    """Replace the active dataset directory in one rename so a failure never leaves it half-written."""
    old = ACTIVE_DIR.parent / ".active_old"
    if old.exists():
        shutil.rmtree(old)
    if ACTIVE_DIR.exists():
        os.replace(ACTIVE_DIR, old)
    os.replace(new_dir, ACTIVE_DIR)
    if old.exists():
        shutil.rmtree(old)
