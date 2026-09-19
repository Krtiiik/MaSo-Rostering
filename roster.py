#!/usr/bin/env python3
"""Thin backward-compatible shim: ``python roster.py buildings.yaml helpers.csv -o out.xlsx``
is equivalent to ``python -m rostering.cli solve buildings.yaml helpers.csv -o out.xlsx``.
"""
import sys

from rostering.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["solve", *sys.argv[1:]]))
