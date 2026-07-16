"""Minimal timestamped workspaces for ChipSeeker Ultra Search tasks."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def safe_direction_name(direction):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(direction or "").strip())
    text = re.sub(r"\s+", "_", text).strip(" ._")
    text = re.sub(r"_+", "_", text)
    return (text or "untitled_direction")[:72]


def create_workspace(direction, root, created_at=None):
    created_at = created_at or datetime.now()
    root = Path(root)
    folder_name = f"{created_at.strftime('%Y%m%d_%H%M%S')}_{safe_direction_name(direction)}"
    workspace = root / folder_name
    suffix = 2
    while workspace.exists():
        workspace = root / f"{folder_name}_{suffix}"
        suffix += 1
    workspace.mkdir(parents=True)
    return workspace


def workspace_status(workspace):
    workspace = Path(workspace)
    entries = sorted(path.name for path in workspace.iterdir()) if workspace.is_dir() else []
    return {
        "workspace": str(workspace.resolve()),
        "exists": workspace.is_dir(),
        "entries": entries,
    }
