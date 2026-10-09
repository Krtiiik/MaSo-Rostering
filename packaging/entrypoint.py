"""PyInstaller entry point: bundles the same ``rostering`` CLI (``ingest``,
``solve``, ``serve``) installed by ``pip install .`` into a standalone
executable. See ``packaging/rostering.spec`` and
``.github/workflows/build-executables.yml``.
"""
import multiprocessing
import sys

from rostering.cli import main

if __name__ == "__main__":
    # NiceGUI (via uvicorn) may start helper processes; a frozen executable
    # must not re-run the CLI in them.
    multiprocessing.freeze_support()
    sys.exit(main())
