"""MIDI panic: silence stuck notes and reset controllers."""
from __future__ import annotations

import argparse

import mido

from .common import PORT_HELP, MidiToolError, output_names, parse_channel, resolve_port

ALL_SOUND_OFF = 120
RESET_ALL_CONTROLLERS = 121
ALL_NOTES_OFF = 123


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("panic", help="send All Notes Off / All Sound Off / Reset Controllers")
    p.add_argument("-p", "--port", action="append", help=PORT_HELP + "; repeatable")
    p.add_argument("--all", action="store_true", help="send to every output port")
    p.add_argument("-c", "--channel", type=parse_channel, action="append",
                   help="only these channels (1-16); repeatable. Default: all 16")
    p.add_argument("--hard", action="store_true",
                   help="also send note-off for every note (for devices ignoring CC123)")
    p.add_argument("--no-reset", action="store_true",
                   help="don't send Reset All Controllers (CC121)")
    p.set_defaults(func=run)


def panic_messages(channels, hard: bool, reset: bool) -> list[mido.Message]:
    msgs = []
    for ch in channels:
        msgs.append(mido.Message("control_change", channel=ch, control=ALL_SOUND_OFF, value=0))
        msgs.append(mido.Message("control_change", channel=ch, control=ALL_NOTES_OFF, value=0))
        if reset:
            msgs.append(mido.Message("control_change", channel=ch,
                                     control=RESET_ALL_CONTROLLERS, value=0))
        msgs.append(mido.Message("control_change", channel=ch, control=64, value=0))  # sustain off
        if hard:
            msgs.extend(mido.Message("note_off", channel=ch, note=n, velocity=0) for n in range(128))
    return msgs


def run(args: argparse.Namespace) -> None:
    available = output_names()
    if args.all:
        names = available
    else:
        names = [resolve_port(q, available, "output") for q in (args.port or [None])]
    if not names:
        raise MidiToolError("no MIDI output ports found")
    channels = sorted(set(args.channel)) if args.channel else range(16)
    msgs = panic_messages(channels, hard=args.hard, reset=not args.no_reset)
    for name in names:
        with mido.open_output(name) as out:
            for m in msgs:
                out.send(m)
        print(f"panic sent to '{name}' ({len(msgs)} messages)")
