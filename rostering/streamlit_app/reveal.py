"""Show a file in the system file manager (the app runs on the user's own machine)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def reveal_in_file_manager(path: Path) -> None:
    """Open the file manager at ``path``'s folder, with the file selected where
    the platform allows it."""
    path = Path(path).resolve()
    if sys.platform == "win32":
        # explorer parses its own command line, so the path is quoted by hand.
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
