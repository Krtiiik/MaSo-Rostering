"""Command-line entry points: ``ingest`` (raw survey -> canonical CSV) and
``solve`` (config + helpers CSV -> solved Excel roster)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rostering.config import load_buildings
from rostering.domain import Competition
from rostering.export.excel import write_roster
from rostering.ingest.legacy import load_helpers_csv, write_helpers_csv
from rostering.ingest.raw_survey import parse_raw_survey
from rostering.manual import load_manual_roles
from rostering.solver.model import NoRosterFound, SolverConfig, solve_competition


def _cmd_ingest(args: argparse.Namespace) -> int:
    result = parse_raw_survey(args.raw_survey)
    write_helpers_csv(result.helpers, args.output)
    print(f"Wrote {len(result.helpers)} helpers to {args.output}")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _cmd_solve(args: argparse.Namespace) -> int:
    buildings = load_buildings(args.buildings)
    helpers_result = load_helpers_csv(args.helpers)
    for warning in helpers_result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    comp = Competition(helpers=helpers_result.helpers, buildings=buildings)
    manual = load_manual_roles(args.manual_roles)

    try:
        result = solve_competition(comp, SolverConfig())
    except NoRosterFound as exc:
        print(str(exc), file=sys.stderr)
        return 1

    write_roster(comp, result, manual, args.output)
    print(f"Wrote roster ({result.status}, objective={result.objective_value}) to {args.output}")
    if result.broken_rules:
        print(f"{len(result.broken_rules)} rule(s) had to be bent:", file=sys.stderr)
        for broken in result.broken_rules:
            print(f"  - {broken.line}", file=sys.stderr)
    if result.unsatisfied_friend_pairs:
        print(f"{len(result.unsatisfied_friend_pairs)} friend request(s) unsatisfied:", file=sys.stderr)
        name_by_id = {h.id: h.name for h in comp.helpers}
        for a_id, b_id in result.unsatisfied_friend_pairs:
            print(f"  - {name_by_id.get(a_id, a_id)} / {name_by_id.get(b_id, b_id)}", file=sys.stderr)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.reload:
        # NiceGUI's reloader re-executes the main script, so development runs go
        # through a script of their own (see rostering/webapp/ui/dev_server.py).
        script = Path(__file__).resolve().parent / "webapp" / "ui" / "dev_server.py"
        command = [sys.executable, str(script), "--host", args.host, "--port", str(args.port)]
        return subprocess.call(command + (["--headless"] if args.headless else []))
    # Imported here: the other commands must not need the web stack.
    from rostering.webapp.ui.app import run

    run(host=args.host, port=args.port, show=not args.headless)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MaSo Roster Generator")
    # Not required: a bare `rostering` (e.g. double-clicking the standalone
    # .exe from Explorer) must default to `serve` — see main() below.
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest", help="Convert a raw survey export into the canonical helpers CSV.")
    ingest_parser.add_argument("raw_survey", type=Path, help="Path to the raw survey .xlsx export.")
    ingest_parser.add_argument("--output", "-o", default=Path("helpers.csv"), type=Path)
    ingest_parser.set_defaults(func=_cmd_ingest)

    solve_parser = subparsers.add_parser("solve", help="Solve a roster and export it to Excel.")
    solve_parser.add_argument("buildings", type=Path, help="Path to the buildings/rooms config YAML.")
    solve_parser.add_argument("helpers", type=Path, help="Path to the canonical helpers CSV.")
    solve_parser.add_argument("--output", "-o", default=Path("roster.xlsx"), type=Path)
    solve_parser.add_argument("--manual-roles", type=Path, default=None, help="Optional manual-roles.yaml overlay.")
    solve_parser.set_defaults(func=_cmd_solve)

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
