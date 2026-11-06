"""List available MIDI input and output ports."""
from __future__ import annotations

import argparse

import mido

from .common import input_names, output_names


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("list", help="list MIDI input/output ports")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    print(f"Backend: {mido.backend.name}\n")
    for title, names in (("Inputs", input_names()), ("Outputs", output_names())):
        print(f"{title}:")
        if not names:
            print("  (none)")
        for i, name in enumerate(names):
            print(f"  [{i}] {name}")
        print()
    print("Use the index or part of the name with --port, e.g. --port 0 or --port \"clarett\"")
