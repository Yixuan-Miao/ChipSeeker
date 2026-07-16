#!/usr/bin/env python3
"""Create or inspect a minimal private Ultra Search workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.paths import DATA_DIR
from chipseeker.ultra_workspace import create_workspace, workspace_status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage persistent local Ultra Search research workspaces.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="Create an empty timestamped workspace.")
    create_parser.add_argument("--direction", required=True)
    create_parser.add_argument("--root", default=str(Path(DATA_DIR) / "ultra_research"))
    status_parser = subparsers.add_parser("status", help="Check an existing research workspace.")
    status_parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)

    if args.command == "create":
        workspace = create_workspace(args.direction, args.root)
        payload = workspace_status(workspace)
    else:
        payload = workspace_status(args.workspace)
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
