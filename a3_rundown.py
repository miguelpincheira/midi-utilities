#!/usr/bin/env python
"""AdrenaLinn III rundown.

  1) preset 7          2) tempo 150 BPM     3) start drumbeat    4) wait 5 s
  5) tempo 120 BPM     6) wait 5 s          7) preset 21         8) wait 5 s
  9) stop drumbeat

Tempo is set according to the A3's System > MIDI Sync setting (read at startup):
  * Sync In / In-Out -> a MIDI clock is sent at the tempo (nothing stored on the A3)
  * Sync ---         -> the A3 ignores clock, so its global tempo is set by SysEx;
                        the original tempo is restored at the end (System params are
                        saved by the A3 immediately)
Force a method with --mode clock|sysex.

The drumbeat is started/stopped with CC80 (the A3's default MIDI foot switch for
"Start/stop drumbeat"; 127 = start, 0 = stop). MIDI Start/Stop is ignored by the A3
when Sync is '---' (firmware 3.03); use --realtime to send those instead.

Usage:  .venv/bin/python a3_rundown.py [--port NAME] [--mode auto|clock|sysex] [--wait 5]
"""
from __future__ import annotations

import argparse
import sys
import time

import mido

from midi_tools.a3 import A3Link
from midi_tools.clock import LockedSender, MidiClock
from midi_tools.common import PORT_HELP, MidiToolError
from midi_tools.devices import adrenalinn3 as a3

# ---------------------------------------------------------------- the rundown
PRESET_A = 7
PRESET_B = 21
TEMPO_A = 150
TEMPO_B = 120


def log(t0: float, text: str) -> None:
    print(f"[{time.perf_counter() - t0:6.2f}s] {text}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", help=PORT_HELP)
    ap.add_argument("--mode", choices=["auto", "clock", "sysex"], default="auto",
                    help="how to set the tempo (default: auto, from the A3 Sync setting)")
    ap.add_argument("--wait", type=float, default=5.0, help="seconds per wait step (default 5)")
    ap.add_argument("--realtime", action="store_true",
                    help="start/stop with MIDI Start/Stop instead of CC80 (needs Sync In; "
                         "ignored by the A3 when Sync is ---)")
    args = ap.parse_args()

    with A3Link(args.port) as link:
        send = LockedSender(link.out)
        sp = link.system() if link.inp is not None else None

        mode = args.mode
        if mode == "auto":
            if sp is None:
                print("note: no reply from the A3, can't read its Sync setting -> using MIDI clock")
                mode = "clock"
            else:
                mode = "sysex" if sp.get("sync") == 0 else "clock"
        print(f"tempo mode: {mode}"
              + (f" (A3 Sync = {a3.SYNC_NAMES.get(sp['sync'], sp['sync'])})" if sp else ""))
        if mode == "sysex" and sp and sp.get("tempo_source") != 0:
            print("WARNING: A3 Tempo Source is not 'system tempo'; the global tempo change "
                  "may not be heard. (System > Tempo Source)")
        original_tempo = sp.get("global_tempo") if sp else None

        if args.realtime:
            start_msg, stop_msg = mido.Message("start"), mido.Message("stop")
        else:
            start_msg, stop_msg = a3.drumbeat_start(), a3.drumbeat_stop()
        print("start/stop via " + ("MIDI Start/Stop" if args.realtime
                                   else f"CC{a3.CC_START_STOP} (127=start, 0=stop)"))

        clock: MidiClock | None = None

        def set_tempo(bpm: int) -> None:
            nonlocal clock
            if mode == "clock":
                if clock is None:
                    clock = MidiClock(send, bpm).start()
                    time.sleep(0.2)          # let the A3 lock to the clock before Start
                else:
                    clock.set_bpm(bpm)
            else:
                send(a3.set_global_tempo(bpm))

        t0 = time.perf_counter()
        try:
            log(t0, f"1) select preset {PRESET_A}")
            send(a3.select_preset(PRESET_A))
            time.sleep(0.1)

            log(t0, f"2) tempo {TEMPO_A} BPM")
            set_tempo(TEMPO_A)

            log(t0, "3) start drumbeat")
            send(start_msg)

            log(t0, f"4) wait {args.wait:g} s")
            time.sleep(args.wait)

            log(t0, f"5) tempo {TEMPO_B} BPM")
            set_tempo(TEMPO_B)

            log(t0, f"6) wait {args.wait:g} s")
            time.sleep(args.wait)

            log(t0, f"7) select preset {PRESET_B}")
            send(a3.select_preset(PRESET_B))

            log(t0, f"8) wait {args.wait:g} s")
            time.sleep(args.wait)
        except KeyboardInterrupt:
            print("\ninterrupted")
        finally:
            log(t0, "9) stop drumbeat")
            send(stop_msg)
            if clock is not None:
                clock.stop()
            if mode == "sysex" and original_tempo:
                time.sleep(0.05)
                send(a3.set_global_tempo(original_tempo))
                print(f"restored A3 global tempo to {original_tempo} BPM")


if __name__ == "__main__":
    try:
        main()
    except (MidiToolError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
