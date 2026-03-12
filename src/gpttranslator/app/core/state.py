"""Workspace state persistence for CLI pipeline orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WorkspaceState:
    version: int = 1
    initialized: bool = False
    active_book_id: str | None = None
    updated_at: str = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "initialized": self.initialized,
            "active_book_id": self.active_book_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceState":
        return cls(
            version=int(data.get("version", 1)),
            initialized=bool(data.get("initialized", False)),
            active_book_id=str(data["active_book_id"]) if data.get("active_book_id") is not None else None,
            updated_at=str(data.get("updated_at", _now_utc())),
        )


def load_workspace_state(path: Path) -> WorkspaceState:
    """Load state file or return defaults when it does not exist."""

    if not path.exists():
        return WorkspaceState()

    payload = json.loads(path.read_text(encoding="utf-8"))
    return WorkspaceState.from_dict(payload)


def save_workspace_state(path: Path, state: WorkspaceState) -> None:
    """Persist workspace state as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_workspace_initialized(path: Path) -> bool:
    """Return whether workspace state marks project as initialized."""

    return load_workspace_state(path).initialized


def touch_workspace_state(
    path: Path,
    initialized: bool = False,
    active_book_id: str | None = None,
) -> WorkspaceState:
    """Create or update workspace state."""

    state = load_workspace_state(path)
    state.initialized = initialized
    state.active_book_id = active_book_id
    state.updated_at = _now_utc()
    save_workspace_state(path, state)
    return state
