"""Send individual MIDI messages to an output port."""
from __future__ import annotations

import argparse
import time

import mido

from .common import (PORT_HELP, MidiToolError, describe, output_names, parse_7bit, parse_channel,
                     parse_hex_bytes, parse_note, resolve_port)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("send", help="send a MIDI message (note, cc, pc, pitch, sysex, raw)")
    p.add_argument("-p", "--port", help=PORT_HELP)
    p.add_argument("-c", "--channel", type=parse_channel, default=0,
                   help="MIDI channel 1-16 (default 1)")
    kinds = p.add_subparsers(dest="kind", required=True, metavar="KIND")

    n = kinds.add_parser("note", help="note on, wait, note off")
    n.add_argument("note", type=parse_note, nargs="+", help="note number or name (C4=60); several = chord")
    n.add_argument("-v", "--velocity", type=lambda v: parse_7bit(v, "velocity"), default=100)
    n.add_argument("-d", "--duration", type=float, default=0.5, help="seconds (default 0.5)")
    n.add_argument("--hold", action="store_true", help="send note-on only (no note-off)")

    cc = kinds.add_parser("cc", help="control change")
    cc.add_argument("control", type=lambda v: parse_7bit(v, "controller"))
    cc.add_argument("value", type=lambda v: parse_7bit(v, "value"))

    pc = kinds.add_parser("pc", help="program change (0-127 as sent on the wire)")
    pc.add_argument("program", type=lambda v: parse_7bit(v, "program"))
    pc.add_argument("--bank", type=int, metavar="N",
                    help="send bank select first (CC0 = N>>7, CC32 = N&127)")

    pb = kinds.add_parser("pitch", help="pitch bend (-8192..8191)")
    pb.add_argument("value", type=int)

    sx = kinds.add_parser("sysex", help="system exclusive, hex bytes (F0/F7 optional)")
    sx.add_argument("data", nargs="+", help='e.g. "F0 7E 7F 06 01 F7"')

    raw = kinds.add_parser("raw", help="raw bytes, sent as-is")
    raw.add_argument("data", nargs="+", help='e.g. "B0 7B 00"')

    p.set_defaults(func=run)


def build_messages(args: argparse.Namespace) -> list[mido.Message]:
    ch = args.channel
    if args.kind == "cc":
        return [mido.Message("control_change", channel=ch, control=args.control, value=args.value)]
    if args.kind == "pc":
        msgs = []
        if args.bank is not None:
            if not 0 <= args.bank <= 16383:
                raise MidiToolError("bank must be 0-16383")
            msgs += [mido.Message("control_change", channel=ch, control=0, value=args.bank >> 7),
                     mido.Message("control_change", channel=ch, control=32, value=args.bank & 0x7F)]
        return msgs + [mido.Message("program_change", channel=ch, program=args.program)]
    if args.kind == "pitch":
        if not -8192 <= args.value <= 8191:
            raise MidiToolError("pitch must be -8192..8191")
        return [mido.Message("pitchwheel", channel=ch, pitch=args.value)]
    if args.kind == "sysex":
        data = parse_hex_bytes(args.data)
        if data and data[0] == 0xF0:
            data = data[1:]
        if data and data[-1] == 0xF7:
            data = data[:-1]
        if any(b > 0x7F for b in data):
            raise MidiToolError("sysex payload bytes must be 00-7F")
        return [mido.Message("sysex", data=data)]
    if args.kind == "raw":
        try:
            return [mido.Message.from_bytes(parse_hex_bytes(args.data))]
        except ValueError as exc:
            raise MidiToolError(f"invalid raw message: {exc}") from None
    raise AssertionError(args.kind)


def run(args: argparse.Namespace) -> None:
    name = resolve_port(args.port, output_names(), "output")
    with mido.open_output(name) as out:
        if args.kind == "note":
            ons = [mido.Message("note_on", channel=args.channel, note=n, velocity=args.velocity)
                   for n in args.note]
            for m in ons:
                out.send(m)
                print(f"-> {name}: {describe(m)}")
            if args.hold:
                return
            try:
                time.sleep(args.duration)
            finally:  # always release, even on Ctrl+C
                for n in args.note:
                    m = mido.Message("note_off", channel=args.channel, note=n, velocity=0)
                    out.send(m)
                    print(f"-> {name}: {describe(m)}")
            return
        for m in build_messages(args):
            out.send(m)
            print(f"-> {name}: {describe(m)}")
