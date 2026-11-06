"""Shared helpers: port lookup, note names, hex parsing, message formatting."""
from __future__ import annotations

import argparse
import re
import sys

import mido

from .config import DEFAULT_PORT

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class MidiToolError(argparse.ArgumentTypeError):
    """User-facing error (bad port name, bad argument, ...).

    Subclasses ArgumentTypeError so argparse ``type=`` converters raising it
    produce a clean usage error instead of a traceback.
    """


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- ports

def input_names() -> list[str]:
    return mido.get_input_names()


def output_names() -> list[str]:
    return mido.get_output_names()


PORT_HELP = f"MIDI port: index, name or name substring (default: '{DEFAULT_PORT}', env PYMIDI_PORT)"


def resolve_port(query: str | None, names: list[str], kind: str) -> str:
    """Find a port by index (``0``), exact name, or case-insensitive substring.

    If ``query`` is None, ``config.DEFAULT_PORT`` is used (strictly: we never
    silently fall back to another device).
    """
    if not names:
        raise MidiToolError(f"no MIDI {kind} ports found")
    if query is None:
        query = DEFAULT_PORT
        if not any(query.lower() in n.lower() for n in names) and query not in names:
            raise MidiToolError(
                f"default {kind} port '{query}' not found. Use --port or set PYMIDI_PORT. "
                f"Available: {names}")
    if query.isdigit():
        idx = int(query)
        if 0 <= idx < len(names):
            return names[idx]
        raise MidiToolError(f"{kind} port index {idx} out of range (0..{len(names) - 1})")
    if query in names:
        return query
    matches = [n for n in names if query.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise MidiToolError(f"no {kind} port matches '{query}'. Available: {names}")
    raise MidiToolError(f"'{query}' matches several {kind} ports: {matches}")


# --------------------------------------------------------------------------- values

def parse_note(value: str) -> int:
    """Parse a MIDI note number or name (``60``, ``C4``, ``F#3``, ``Bb-1``).

    Convention: C4 = 60 (middle C). Some manufacturers (e.g. Yamaha) call 60 "C3".
    """
    value = value.strip()
    if value.lstrip("-").isdigit():
        n = int(value)
    else:
        m = _NOTE_RE.match(value)
        if not m:
            raise MidiToolError(f"invalid note '{value}' (use 0-127 or a name like C4, F#3)")
        letter, accidental, octave = m.groups()
        n = _SEMITONE[letter.upper()] + (12 * (int(octave) + 1))
        n += {"#": 1, "b": -1, "": 0}[accidental]
    if not 0 <= n <= 127:
        raise MidiToolError(f"note {value} is outside the MIDI range 0-127")
    return n


def note_name(n: int) -> str:
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def parse_channel(value: str) -> int:
    """User-facing channel 1-16 -> mido channel 0-15."""
    ch = int(value)
    if not 1 <= ch <= 16:
        raise MidiToolError(f"channel must be 1-16, got {ch}")
    return ch - 1


def parse_7bit(value: str, what: str) -> int:
    v = int(value, 0)
    if not 0 <= v <= 127:
        raise MidiToolError(f"{what} must be 0-127, got {v}")
    return v


def parse_hex_bytes(parts: list[str]) -> list[int]:
    """Parse ``["F0", "7E", "7F06", "01", "F7"]`` or ``["F0 7E 7F 06 01 F7"]`` into ints."""
    text = "".join(parts).replace(" ", "").replace(",", "").replace("0x", "")
    if len(text) % 2:
        raise MidiToolError("hex data must have an even number of digits")
    try:
        return list(bytes.fromhex(text))
    except ValueError as exc:
        raise MidiToolError(f"invalid hex data: {exc}") from None


def hex_str(data) -> str:
    return " ".join(f"{b:02X}" for b in data)


# --------------------------------------------------------------------------- display

def describe(msg: mido.Message) -> str:
    """Human-readable one-line description, channels shown as 1-16."""
    t = msg.type
    ch = f"ch{msg.channel + 1:<2}" if hasattr(msg, "channel") else "    "
    if t in ("note_on", "note_off"):
        detail = f"{note_name(msg.note):<4} ({msg.note:3}) vel {msg.velocity}"
    elif t == "control_change":
        detail = f"CC {msg.control:3} = {msg.value}"
    elif t == "program_change":
        detail = f"program {msg.program} (1-based: {msg.program + 1})"
    elif t == "pitchwheel":
        detail = f"pitch {msg.pitch:+d}"
    elif t == "aftertouch":
        detail = f"pressure {msg.value}"
    elif t == "polytouch":
        detail = f"{note_name(msg.note)} pressure {msg.value}"
    elif t == "sysex":
        detail = f"F0 {hex_str(msg.data)} F7  ({len(msg.data) + 2} bytes)"
    else:
        detail = " ".join(f"{k}={v}" for k, v in msg.dict().items() if k not in ("type", "time"))
    return f"{ch} {t:<15} {detail}"
