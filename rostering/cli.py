"""Command-line entry point: ``serve`` runs the web app (the default)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.reload:
        # NiceGUI's reloader re-executes the main script, so development runs go
        # through a script of their own (see rostering/webapp/ui/dev_server.py).
        script = Path(__file__).resolve().parent / "webapp" / "ui" / "dev_server.py"
        command = [sys.executable, str(script), "--host", args.host, "--port", str(args.port)]
        server = subprocess.Popen(command + (["--headless"] if args.headless else []))
        while True:
            # Ctrl+C reaches the child too (same console); let it shut down
            # instead of abandoning it mid-way.
            try:
                server.wait()
                break
            except KeyboardInterrupt:
                continue
        print("Rostering stopped.")
        return 0
    # Imported here so `--help` and `--reload` (which only launch a child) stay light.
    from rostering.webapp.ui.app import run

    try:
        run(host=args.host, port=args.port, show=not args.headless)
    except KeyboardInterrupt:
        # Ctrl+C: the server has already shut down cleanly; uvicorn only
        # re-raises the signal afterwards. No traceback for that.
        pass
    print("Rostering stopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MaSo Roster Generator")
    # Not required: a bare `rostering` (e.g. double-clicking the standalone
    # .exe from Explorer) must default to `serve` — see main() below.
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the interactive web app.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development).")
    serve_parser.add_argument(
        "--headless", action="store_true", help="Don't auto-open a browser tab (for scripted/agent runs)."
    )
    serve_parser.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        # No subcommand at all (double-clicking the standalone .exe from
        # Explorer launches it with no argv) -> default to `serve` with a
        # visible browser tab, so a non-technical user just double-clicks.
        argv = ["serve"]
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
