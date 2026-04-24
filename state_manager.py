from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, IO
import fcntl
import json
import os
import shutil
import tempfile


@dataclass(slots=True)
class WikiState:
    version: int = 1
    last_run: str = ""
    last_lint: str = ""
    notes: dict[str, dict[str, Any]] = field(default_factory=dict)
    processed_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    folders_created: list[str] = field(default_factory=list)


def _state_backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _coerce_state(data: dict[str, Any]) -> WikiState:
    return WikiState(
        version=int(data.get("version", 1)),
        last_run=data.get("last_run", ""),
        last_lint=data.get("last_lint", ""),
        notes=dict(data.get("notes", {})),
        processed_files=dict(data.get("processed_files", {})),
        folders_created=list(data.get("folders_created", [])),
    )


def load_state(path: str | Path) -> WikiState:
    state_path = Path(path).expanduser().resolve()
    if not state_path.exists():
        return WikiState()

    try:
        return _coerce_state(json.loads(state_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        backup_path = _state_backup_path(state_path)
        if backup_path.exists():
            return _coerce_state(json.loads(backup_path.read_text(encoding="utf-8")))
        raise


def save_state(path: str | Path, state: WikiState) -> None:
    state_path = Path(path).expanduser().resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), indent=2, sort_keys=True)

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=state_path.parent, delete=False
    ) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = Path(tmp.name)

    shutil.move(str(tmp_name), state_path)
    shutil.copy2(state_path, _state_backup_path(state_path))


def acquire_lock(lock_path: str | Path) -> IO[str] | None:
    resolved = Path(lock_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(resolved, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file
