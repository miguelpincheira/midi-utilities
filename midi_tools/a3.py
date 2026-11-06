"""AdrenaLinn III (A3) tools: identify, status, drumbeat audition/inspection, MIDI drums test.

Wiring assumed: Clarett MIDI OUT -> A3 MIDI IN (required)
                A3 MIDI OUT -> Clarett MIDI IN (optional; needed for replies:
                identity, status, drumbeat dumps)
"""
from __future__ import annotations

import argparse
import time

import mido

from .common import (PORT_HELP, MidiToolError, hex_str, input_names, output_names,
                     parse_channel, resolve_port)
from .devices import adrenalinn3 as a3

REPLY_TIMEOUT = 1.0


# ----------------------------------------------------------------------------- link

class A3Link:
    """Output (+ optional input) to the A3 through the same interface."""

    def __init__(self, port: str | None, need_input: bool = False):
        self.out = mido.open_output(resolve_port(port, output_names(), "output"))
        self.inp = None
        try:
            self.inp = mido.open_input(resolve_port(port, input_names(), "input"))
        except MidiToolError:
            if need_input:
                raise
        except (OSError, IOError):
            if need_input:
                raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self.out.close()
        if self.inp:
            self.inp.close()

    def send(self, msg: mido.Message) -> None:
        self.out.send(msg)

    def request(self, msg: mido.Message, accept, timeout: float = REPLY_TIMEOUT):
        """Send ``msg`` and return the first ``accept(reply)`` result that is not None."""
        if self.inp is None:
            return None
        for _ in self.inp.iter_pending():   # discard stale input
            pass
        self.send(msg)
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            for m in self.inp.iter_pending():
                result = accept(m)
                if result is not None:
                    return result
            time.sleep(0.002)
        return None

    # --- A3 requests
    def identify(self):
        return self.request(a3.IDENTITY_REQUEST, a3.parse_identity)

    def system(self):
        def accept(m):
            p = a3.parse(m)
            return a3.decode_system(p[1]) if p and p[0] == a3.MsgId.SYSTEM else None
        return self.request(a3.request_system(), accept)

    def drumbeat(self, n: int | None):
        """Dump drumbeat ``n`` (or the edit buffer if None). Returns (Drumbeat, sysex msg)."""
        want = a3.MsgId.DRUMBEAT if n is not None else a3.MsgId.DRUMBEAT_EDIT
        req = a3.request_drumbeat(n) if n is not None else a3.request_drumbeat_edit_buffer()

        def accept(m):
            p = a3.parse(m)
            return (a3.Drumbeat.from_payload(p[1]), m) if p and p[0] == want else None
        return self.request(req, accept)


def precise_sleep_until(t: float) -> None:
    while True:
        remaining = t - time.perf_counter()
        if remaining <= 0:
            return
        time.sleep(remaining - 0.0015 if remaining > 0.002 else 0)


def start_stop_msgs(realtime: bool):
    if realtime:
        return mido.Message("start"), mido.Message("stop")
    return a3.drumbeat_start(), a3.drumbeat_stop()


def play_transport(link: A3Link, bars: float, bpm: float, clock: bool,
                   realtime: bool = False) -> None:
    """Start, run for ``bars`` (driving MIDI clock at ``bpm`` if ``clock``), Stop.

    Start/stop uses CC80 unless ``realtime`` (MIDI Start/Stop, needs Sync In).
    Always sends Stop, even on Ctrl+C.
    """
    start, stop = start_stop_msgs(realtime)
    try:
        link.send(start)
        if clock:
            interval = 60.0 / (bpm * 24)
            total = round(bars * a3.CLOCKS_PER_BAR)
            t0 = time.perf_counter()
            tick = mido.Message("clock")
            for i in range(total):
                precise_sleep_until(t0 + i * interval)
                link.send(tick)
            precise_sleep_until(t0 + total * interval)
        else:
            time.sleep(bars * 4 * 60.0 / bpm)
    finally:
        link.send(stop)


def parse_range(spec: str) -> list[int]:
    """'0-9,15,20-22' -> [0..9, 15, 20, 21, 22]."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.extend(range(a, b + 1) if a <= b else range(a, b - 1, -1))
        else:
            out.append(int(part))
    bad = [n for n in out if not 0 <= n < a3.NUM_DRUMBEATS]
    if bad:
        raise MidiToolError(f"drumbeat numbers must be 0-199, got {bad}")
    if not out:
        raise MidiToolError("empty drumbeat list")
    return out


def effective_tempo(beat, clock: bool, tempo_source: int, global_tempo) -> float:
    """Tempo to use when --bpm is not given.

    With MIDI clock, the A3 follows us, so use the drumbeat's own tempo. Without
    clock, match what the A3 will play: System 'Tempo Source' 0 = global tempo,
    1 = drumbeat tempo, 2 = preset tempo (unknown here -> global tempo).
    """
    beat_tempo = beat.tempo if beat and 30 <= beat.tempo <= 250 else None
    if not clock and tempo_source != 1 and global_tempo:
        return global_tempo
    return beat_tempo or global_tempo or 100


def warn_no_input(link: A3Link) -> None:
    if link.inp is None:
        print("note: no MIDI input on the interface; replies from the A3 can't be read.")


# ----------------------------------------------------------------------------- commands

def cmd_identify(args) -> None:
    with A3Link(args.port, need_input=True) as link:
        ident = link.identify()
        if ident is None:
            raise MidiToolError(
                "no Identity Reply. Check: Clarett MIDI OUT -> A3 MIDI IN and "
                "A3 MIDI OUT -> Clarett MIDI IN, A3 powered on.")
        kind = "AdrenaLinn III" if ident["is_a3"] else "unknown Roger Linn device"
        print(f"{kind}: firmware {ident['version']}, device id {ident['device_id']}")


def cmd_status(args) -> None:
    with A3Link(args.port, need_input=True) as link:
        ident = link.identify()
        print(f"identity: {'firmware ' + ident['version'] if ident else 'NO REPLY'}")
        sp = link.system()
        if sp is None:
            raise MidiToolError("no reply to Request System Parameters")
        print("system parameters:")
        print("\n".join(a3.describe_system(sp)))
        if args.raw:
            print("  raw:", hex_str(sp["_raw"]))


def print_drumbeat(n, beat: a3.Drumbeat, raw: bool) -> None:
    title = f"Drumbeat {n}" if n is not None else "Drumbeat edit buffer"
    print(f"== {title} ==")
    print("\n".join(beat.summary()))
    print("\n".join(beat.grid()))
    if raw:
        print("raw:", hex_str(beat.raw))


def cmd_show(args) -> None:
    numbers = parse_range(args.beats) if args.beats != "edit" else [None]
    saved = []
    with A3Link(args.port, need_input=True) as link:
        for n in numbers:
            res = link.drumbeat(n)
            if res is None:
                print(f"drumbeat {n}: NO REPLY")
                continue
            beat, msg = res
            print_drumbeat(n, beat, args.raw)
            print()
            saved.append(msg)
    if args.save and saved:
        mido.write_syx_file(args.save, saved)
        print(f"saved {len(saved)} drumbeat dump(s) to {args.save}")


def cmd_play(args) -> None:
    numbers = parse_range(args.beats)
    results: dict[int, str] = {}
    with A3Link(args.port) as link:
        warn_no_input(link)
        sp = link.system() if link.inp is not None else None
        if link.inp is not None and sp is None:
            print("note: A3 doesn't answer (A3 MIDI OUT not connected?); playing without dumps.")
            args.no_dump = True
        if sp and args.clock and sp.get("sync") == 0:
            print("note: A3 MIDI Sync is '---' (ignores MIDI clock) -> using Start/Stop at the "
                  "A3's internal tempo.\n      Set System > MIDI Sync to 'In' to drive the "
                  "tempo from here.")
            args.clock = False
        tempo_source = sp.get("tempo_source", 1) if sp else 1
        global_tempo = sp.get("global_tempo") if sp else None
        print(f"Auditioning {len(numbers)} drumbeat(s), {args.bars:g} bar(s) each, "
              f"{'MIDI clock' if args.clock else 'internal tempo'}"
              f"{', interactive' if args.interactive else ''}. Ctrl+C to abort.\n")
        idx = 0
        try:
            while idx < len(numbers):
                n = numbers[idx]
                if args.select == "sysex":
                    link.send(a3.select_drumbeat(n))
                else:
                    for m in a3.select_drumbeat_pc(n, args.channel):
                        link.send(m)
                time.sleep(0.05)

                beat = None
                if not args.no_dump and link.inp is not None:
                    res = link.drumbeat(n)
                    beat = res[0] if res else None
                bpm = args.bpm or effective_tempo(beat, args.clock, tempo_source, global_tempo)

                if beat:
                    print_drumbeat(n, beat, raw=False)
                    empty = [v for v, c in beat.hit_count().items() if c == 0]
                    if all(c == 0 for c in beat.hit_count().values()):
                        print("  WARNING: drumbeat is empty (no hits)")
                    elif empty:
                        print(f"  (no hits on: {', '.join(empty)})")
                else:
                    print(f"== Drumbeat {n} ==" + ("" if args.no_dump else "  (no dump reply)"))
                print(f"  playing at {bpm:g} BPM ...", flush=True)
                play_transport(link, args.bars, bpm, args.clock, args.realtime)

                if args.interactive:
                    ans = input("  [Enter]=ok/next  b=bad  r=replay  q=quit > ").strip().lower()
                    if ans == "r":
                        continue
                    if ans == "q":
                        break
                    results[n] = "bad" if ans == "b" else "ok"
                else:
                    results[n] = "played"
                    if idx < len(numbers) - 1:
                        time.sleep(args.pause)
                idx += 1
                print()
        except KeyboardInterrupt:
            link.send(start_stop_msgs(args.realtime)[1])
            print("\naborted.")
        if sp and "active_drumbeat" in sp and not args.keep:
            link.send(a3.select_drumbeat(sp["active_drumbeat"]))
            print(f"restored active drumbeat {sp['active_drumbeat']}")
    bad = [n for n, r in results.items() if r == "bad"]
    print(f"Done: {len(results)} drumbeat(s) tested."
          + (f" Marked bad: {bad}" if bad else ""))


def cmd_drums(args) -> None:
    with A3Link(args.port) as link:
        warn_no_input(link)
        if link.inp is not None:
            sp = link.system()
            if sp and sp.get("midi_drums") == 0:
                print("WARNING: A3 'MIDI Drums' is OFF; notes won't trigger drums. "
                      "Enable it in System > Details > MIDI Drums.")
            elif sp and "midi_drums" in sp:
                print("A3 MIDI Drums: ON")
        ch = args.channel
        print(f"Triggering A3 drum voices via MIDI notes on channel {ch + 1}. Ctrl+C to stop.\n")
        try:
            for _ in range(args.repeat):
                for voice, note in a3.DRUM_NOTES.items():
                    zones = a3.VELOCITY_ZONES.items() if not voice.startswith("perc") \
                        else [("fixed", 100)]
                    for zone, vel in zones:
                        print(f"  {voice:<6} note {note}  {zone:<6} (vel {vel})", flush=True)
                        for _ in range(args.hits):
                            link.send(mido.Message("note_on", channel=ch, note=note, velocity=vel))
                            time.sleep(0.05)
                            link.send(mido.Message("note_off", channel=ch, note=note, velocity=0))
                            time.sleep(args.gap)
                    time.sleep(args.gap)
        except KeyboardInterrupt:
            print("\nstopped.")


def cmd_transport(args) -> None:
    with A3Link(args.port) as link:
        if args.action == "select":
            if args.number is None:
                raise MidiToolError("select needs a drumbeat number")
            link.send(a3.select_drumbeat(args.number))
            print(f"selected drumbeat {args.number}")
        elif args.action == "continue" or args.realtime:
            link.send(mido.Message(args.action))
            print(f"sent MIDI {args.action}")
        else:
            msg = a3.drumbeat_start() if args.action == "start" else a3.drumbeat_stop()
            link.send(msg)
            print(f"sent {args.action} (CC{msg.control}={msg.value})")


# ----------------------------------------------------------------------------- parser

def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("a3", help="AdrenaLinn III tools (drumbeats, status, MIDI drums)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-p", "--port", help=PORT_HELP)
    cmds = p.add_subparsers(dest="a3_command", required=True, metavar="ACTION")

    c = cmds.add_parser("identify", help="Identity Request: check the A3 answers")
    c.set_defaults(func=cmd_identify)

    c = cmds.add_parser("status", help="identity + system parameters (channel, sync, MIDI drums...)")
    c.add_argument("--raw", action="store_true")
    c.set_defaults(func=cmd_status)

    c = cmds.add_parser("show", help="dump drumbeat(s) and print the step grid")
    c.add_argument("beats", help="drumbeat numbers, e.g. 12 or 0-9,15; or 'edit' for edit buffer")
    c.add_argument("--raw", action="store_true", help="also print decoded bytes")
    c.add_argument("--save", metavar="FILE.syx", help="save the dumps to a .syx file")
    c.set_defaults(func=cmd_show)

    c = cmds.add_parser("play", help="audition drumbeats: select, play N bars, stop, next")
    c.add_argument("beats", nargs="?", default="0-199", help="e.g. 0-9,15 (default 0-199)")
    c.add_argument("--bars", type=float, default=4, help="bars per drumbeat (default 4 = 2 loops)")
    c.add_argument("--bpm", type=float, help="tempo (default: drumbeat's own tempo, else 100)")
    c.add_argument("--no-clock", dest="clock", action="store_false",
                   help="don't send MIDI clock; just Start/Stop at the A3 internal tempo")
    c.add_argument("--select", choices=["sysex", "pc"], default="sysex",
                   help="selection method: SysEx Select Drumbeat (default) or CC32+Program Change")
    c.add_argument("-c", "--channel", type=parse_channel, default=0,
                   help="channel for --select pc (default 1)")
    c.add_argument("--pause", type=float, default=0.5, help="seconds between drumbeats")
    c.add_argument("-i", "--interactive", action="store_true",
                   help="after each drumbeat ask ok/bad/replay/quit, report bad ones at the end")
    c.add_argument("--no-dump", action="store_true", help="don't request/print drumbeat data")
    c.add_argument("--realtime", action="store_true",
                   help="start/stop with MIDI Start/Stop instead of CC80 (needs Sync In)")
    c.add_argument("--keep", action="store_true",
                   help="stay on the last tested drumbeat (default: restore the previous one)")
    c.set_defaults(func=cmd_play)

    c = cmds.add_parser("drums", help="trigger each drum voice via MIDI notes (needs MIDI Drums ON)")
    c.add_argument("-c", "--channel", type=parse_channel, default=0, help="channel (default 1)")
    c.add_argument("--hits", type=int, default=2, help="hits per velocity zone (default 2)")
    c.add_argument("--gap", type=float, default=0.35, help="seconds between hits")
    c.add_argument("--repeat", type=int, default=1, help="repeat the whole test N times")
    c.set_defaults(func=cmd_drums)

    c = cmds.add_parser("transport", help="send start / stop / continue, or select a drumbeat")
    c.add_argument("action", choices=["start", "stop", "continue", "select"])
    c.add_argument("number", nargs="?", type=int, help="drumbeat for 'select'")
    c.add_argument("--realtime", action="store_true",
                   help="use MIDI Start/Stop instead of CC80 for start/stop")
    c.set_defaults(func=cmd_transport)
