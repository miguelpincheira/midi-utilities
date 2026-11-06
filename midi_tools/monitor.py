"""Live monitor of incoming MIDI messages on one, several, or all input ports."""
from __future__ import annotations

import argparse
import signal
import threading
import time

import mido

from .common import PORT_HELP, MidiToolError, describe, input_names, parse_channel, resolve_port

NOISY = {"clock", "active_sensing"}


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("monitor", help="print incoming MIDI messages")
    p.add_argument("-p", "--port", action="append", help=PORT_HELP + "; repeatable")
    p.add_argument("--all", action="store_true", help="monitor every input port")
    p.add_argument("--virtual", metavar="NAME",
                   help="create a virtual input port with this name and monitor it")
    p.add_argument("-c", "--channel", type=parse_channel, action="append",
                   help="only show these channels (1-16); repeatable")
    p.add_argument("--show-clock", action="store_true",
                   help="also show clock / active-sensing messages (hidden by default)")
    p.add_argument("--raw", action="store_true", help="also print raw hex bytes")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    if args.virtual:
        names = []
    elif args.all:
        names = input_names()
        if not names:
            raise MidiToolError("no MIDI input ports found (use --virtual NAME to create one)")
    else:
        names = [resolve_port(q, input_names(), "input") for q in (args.port or [None])]

    channels = set(args.channel) if args.channel else None
    start = time.perf_counter()
    lock = threading.Lock()
    counts: dict[str, int] = {}

    def make_callback(label: str):
        def callback(msg: mido.Message) -> None:
            if msg.type in NOISY and not args.show_clock:
                counts[msg.type] = counts.get(msg.type, 0) + 1
                return
            if channels is not None and getattr(msg, "channel", None) not in channels:
                return
            line = f"{time.perf_counter() - start:10.4f}  {label:<24.24} {describe(msg)}"
            if args.raw:
                line += f"   [{msg.hex()}]"
            with lock:
                print(line, flush=True)
        return callback

    def _on_term(signum, frame):  # make `kill` behave like Ctrl+C (prints summary)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_term)

    ports = []
    try:
        if args.virtual:
            ports.append(mido.open_input(args.virtual, virtual=True,
                                         callback=make_callback(args.virtual)))
        for name in names:
            ports.append(mido.open_input(name, callback=make_callback(name)))
        print("Monitoring: " + ", ".join(p.name for p in ports))
        print("Press Ctrl+C to stop.\n")
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in ports:
            p.close()
        if counts:
            print("\nHidden messages: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
