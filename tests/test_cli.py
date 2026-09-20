import argparse

import pytest

from rostering import cli


def test_no_args_defaults_to_serve(monkeypatch):
    """Double-clicking the standalone .exe from Explorer invokes `rostering`
    with no argv at all; that must behave like `rostering serve`."""
    captured: dict = {}

    def fake_cmd_serve(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_cmd_serve", fake_cmd_serve)

    assert cli.main([]) == 0
    assert captured["args"].command == "serve"
    assert captured["args"].host == "127.0.0.1"
    assert captured["args"].headless is False


def test_no_sys_argv_defaults_to_serve(monkeypatch):
    captured: dict = {}

    def fake_cmd_serve(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_cmd_serve", fake_cmd_serve)
    monkeypatch.setattr(cli.sys, "argv", ["rostering"])

    assert cli.main() == 0
    assert captured["args"].command == "serve"


def test_unknown_subcommand_still_errors():
    with pytest.raises(SystemExit):
        cli.main(["not-a-real-command"])


def test_explicit_serve_args_still_parsed(monkeypatch):
    captured: dict = {}

    def fake_cmd_serve(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_cmd_serve", fake_cmd_serve)

    assert cli.main(["serve", "--port", "9000", "--headless"]) == 0
    assert captured["args"].port == 9000
    assert captured["args"].headless is True
