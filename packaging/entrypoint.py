"""PyInstaller entry point: bundles the same ``rostering`` CLI (``ingest``,
``solve``, ``serve``) installed by ``pip install .`` into a standalone
executable. See ``packaging/rostering.spec`` and
``.github/workflows/build-executables.yml``.
"""
import sys

from rostering.cli import main

if __name__ == "__main__":
    sys.exit(main())
