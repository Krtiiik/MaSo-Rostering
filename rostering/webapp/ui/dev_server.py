"""The web app with NiceGUI's auto-reload on code changes, for development:
``rostering serve --reload`` runs this file as a script. NiceGUI's reloader
re-executes the main script in a worker process (and refuses ``python -m``), so
``ui.run`` sits behind this guard in a file of its own rather than in the CLI.

    python rostering/webapp/ui/dev_server.py [--host H] [--port P] [--headless]
"""
import argparse
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]  # rostering/
# Run as a script, this file's own folder is on sys.path; the checkout's root
# must be first so this very checkout's rostering is the one imported.
sys.path.insert(0, str(PACKAGE.parent))

from rostering.webapp.ui.app import run  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    parser = argparse.ArgumentParser(prog="dev_server.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--headless", action="store_true")
    args, _ = parser.parse_known_args()
    try:
        run(host=args.host, port=args.port, show=not args.headless, reload=True, watch=PACKAGE)
    except KeyboardInterrupt:
        pass  # Ctrl+C: already shut down cleanly (see app.run)
