#!/usr/bin/env python
"""Fix the AdrenaLinn III so it follows a DAW (e.g. Cubase) over MIDI.

Reads the A3 System parameters, sets System > MIDI Sync to 'In' (or In-Out) if
needed, and reads them back to verify. With Sync = '---' the A3 ignores MIDI clock
and MIDI Start/Stop, so DAW sync and tempo-synced effects stop working.

Usage:
  .venv/bin/python a3_fix_midi.py               # ensure Sync = In
  .venv/bin/python a3_fix_midi.py --sync in-out # also send clock from the A3
  .venv/bin/python a3_fix_midi.py --check       # only report, change nothing
"""
from __future__ import annotations

import argparse
import sys
import time

from midi_tools.a3 import A3Link
from midi_tools.common import PORT_HELP, MidiToolError
from midi_tools.devices import adrenalinn3 as a3

SYNC_VALUES = {"in": 1, "in-out": 2}


def report(sp: dict) -> None:
    sync = sp.get("sync")
    print(f"  MIDI Sync     : {a3.SYNC_NAMES.get(sync, sync)}")
    print(f"  MIDI Channel  : {'ALL (omni)' if sp.get('channel') == 0 else sp.get('channel')}")
    print(f"  Tempo Source  : {a3.TEMPO_SOURCE_NAMES.get(sp.get('tempo_source'), '?')}"
          f"  (global tempo {sp.get('global_tempo')} BPM; ignored while external clock runs)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", help=PORT_HELP)
    ap.add_argument("--sync", choices=SYNC_VALUES, default="in",
                    help="target Sync setting (default: in)")
    ap.add_argument("--check", action="store_true", help="only report, don't change anything")
    args = ap.parse_args()
    target = SYNC_VALUES[args.sync]

    with A3Link(args.port, need_input=True) as link:
        ident = link.identify()
        if ident is None:
            raise MidiToolError("the A3 doesn't answer. Check the MIDI cables both ways and power.")
        print(f"AdrenaLinn III found (firmware {ident['version']})")

        sp = link.system()
        if sp is None:
            raise MidiToolError("no reply to Request System Parameters")
        print("current settings:")
        report(sp)

        if sp.get("sync") == target:
            print(f"\nOK: MIDI Sync is already {a3.SYNC_NAMES[target]}. Nothing to fix on the A3.")
            print("If the DAW still doesn't drive it, check the DAW's MIDI Clock destination "
                  "(Cubase: Studio > Synchronization Setup > MIDI Clock Destinations).")
            return 0
        if args.check:
            print(f"\nNEEDS FIX: MIDI Sync should be {a3.SYNC_NAMES[target]}. "
                  "Run without --check to fix.")
            return 1

        print(f"\nsetting MIDI Sync -> {a3.SYNC_NAMES[target]} ...")
        link.send(a3.set_parameter(a3.ParamArea.SYSTEM, a3.SYS_SYNC, target))
        time.sleep(0.3)

        sp2 = link.system()
        if sp2 is None or sp2.get("sync") != target:
            got = a3.SYNC_NAMES.get(sp2.get("sync"), "?") if sp2 else "no reply"
            raise MidiToolError(f"verification failed (A3 reports Sync = {got}). "
                                "Set it on the panel: System row > MIDI SYNC.")
        print("verified, settings now:")
        report(sp2)
        print("\nFixed. Press play in the DAW; the A3 tempo display should show external sync.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (MidiToolError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
