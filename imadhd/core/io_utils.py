"""Small filesystem helpers shared by local JSON stores and diagnostics."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path, obj: Any, *, indent: int | None = 2) -> None:
    """Write JSON through a sibling temp file and atomically replace the target."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def debug_log(line: str, *, name: str | None = None) -> None:
    """Append a diagnostic line to ~/.imadhd/debug.log, swallowing log failures."""
    try:
        text = f"[{name}] {line}" if name else line
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
