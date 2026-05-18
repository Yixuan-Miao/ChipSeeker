import os
from pathlib import Path


if os.name == "nt":
    _original_mkdir = Path.mkdir

    def _pytest_windows_safe_mkdir(self, mode=0o777, parents=False, exist_ok=False):
        # Python 3.12 can create Windows 0o700 directories with an ACL that a
        # non-elevated admin shell cannot read. Pytest uses 0o700 for temp dirs,
        # so normalize only that test-time mode on Windows.
        if mode == 0o700:
            mode = 0o777
        return _original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    Path.mkdir = _pytest_windows_safe_mkdir
