#!/usr/bin/env python3
"""Run the configured ChipSeeker mixed-retrieval collector from any workspace."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"F:\Papers_Embedding\SearchPaperByEmbedding-main")
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
COLLECT_CLI = PROJECT_ROOT / "scripts" / "chipseeker_agent_collect.py"


def main() -> int:
    missing = [str(path) for path in (PROJECT_PYTHON, COLLECT_CLI) if not path.is_file()]
    if missing:
        print("ChipSeeker is not ready; missing: " + ", ".join(missing), file=sys.stderr)
        return 2
    return subprocess.run([str(PROJECT_PYTHON), str(COLLECT_CLI), *sys.argv[1:]], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
