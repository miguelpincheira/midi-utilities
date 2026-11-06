"""Entry point: ``python -m midi_tools <command> ...``"""
from __future__ import annotations

import argparse

from . import a3, list_ports, monitor, panic, send
from .common import MidiToolError, die


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="midi_tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in (list_ports, monitor, send, panic, a3):
        module.add_parser(sub)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except MidiToolError as exc:
        die(str(exc))
    except (ValueError, OSError) as exc:  # backend / port open errors
        die(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
