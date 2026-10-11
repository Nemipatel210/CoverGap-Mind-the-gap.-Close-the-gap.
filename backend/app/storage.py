"""File-based persistence with atomic writes (write temp file, fsync, os.replace)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .config import ACTIVE_DIR, DEMO_DIR, STAGING_DIR, STATE_DIR

LOCK = threading.RLock()


def _retry(fn, attempts: int = 40, delay: float = 0.05):
    """Windows can briefly refuse to replace or read a file that another reader, an antivirus scanner or the
    search indexer has open ("Access is denied"). Retry for up to ~2 seconds instead of failing the request."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write_text(path: Path, text: str) -> None:
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            _retry(lambda: os.replace(tmp, path))
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise


def read_json(name: str, default: Any) -> Any:
    path = STATE_DIR / name
    with LOCK:
        if not path.exists():
            return json.loads(json.dumps(default))
        text = _retry(lambda: path.read_text(encoding="utf-8"))
        try:
            return json.loads(text) if text.strip() else json.loads(json.dumps(default))
        except json.JSONDecodeError:
            # Never silently treat a damaged state file as empty (a later save would wipe it): keep a copy.
            shutil.copy(path, path.with_suffix(".corrupt.json"))
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
