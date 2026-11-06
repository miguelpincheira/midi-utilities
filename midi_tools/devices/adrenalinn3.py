"""Roger Linn Design AdrenaLinn III ("A3") MIDI protocol.

Source: docs/hardware/Adrenalinn_iii_midi_implementation,_8-1-07.pdf (firmware 3.0)
and the user's manual v3.02 (MIDI Drums note map, sync rules).

Pure protocol code: message builders, parsers, 7-bit (un)packing and data-structure
decoders. No port handling here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import mido

# ----------------------------------------------------------------------------- constants

MANUFACTURER = [0x00, 0x01, 0x37]  # Roger Linn Design
PRODUCT_ID = 0x03                  # AdrenaLinn III
FILE_VERSION = 0x01
HEADER = MANUFACTURER + [PRODUCT_ID, FILE_VERSION]

NUM_DRUMBEATS = 200
NUM_PRESETS = 200
BARS_PER_DRUMBEAT = 2              # every drumbeat is a 2-bar loop (4/4)
CLOCKS_PER_BAR = 96                # 24 ppqn * 4 beats


class MsgId(IntEnum):
    RECEIVE_PARAMETER = 1
    PRESET = 2
    DRUMBEAT = 3
    REQUEST_PRESET = 5
    REQUEST_DRUMBEAT = 6
    SELECT_DRUMBEAT = 8
    SELECT_PRESET = 9
    REQUEST_PRESET_EDIT = 10
    PRESET_EDIT = 11
    REQUEST_DRUMBEAT_EDIT = 12
    DRUMBEAT_EDIT = 13
    REQUEST_SYSTEM = 14
    SYSTEM = 15
    SAVE_COMPLETE = 17
    FACTORY_INIT = 19   # destructive! not exposed by the CLI


# CC32 values that select what Program Change 0-99 addresses
CC_BANK = 32
BANK_PRESETS_0_99, BANK_PRESETS_100_199, BANK_DRUMBEATS_0_99, BANK_DRUMBEATS_100_199 = 0, 1, 2, 3

# Default MIDI foot-switch CC assignments (System > Foot Switch Source/Dest)
CC_START_STOP = 80
CC_INTRO_END = 81
CC_TAP_TEMPO = 82
CC_LAST_DRUMBEAT = 83

# MIDI Drums (System "MIDI Drums" = ON). Bass/snare/hihat have 3 velocity zones.
DRUM_NOTES = {
    "bass": 36,
    "snare": 38,
    "hihat": 40,
    "perc1": 41,
    "perc2": 43,
    "perc3": 45,
}
VELOCITY_ZONES = {"soft": 30, "medium": 64, "loud": 110}   # 1-42 / 43-84 / 85-127

TIMEBASES = ["8n", "8t", "16n", "16h", "16s", "9", "10", "10h", "10s", "11", "12", "12h",
             "12s", "13", "14", "14h", "14s", "15"]
TIMEBASE_HELP = {
    "8n": "1/8 notes (16 steps)", "8t": "1/8 triplets (24 steps)", "16n": "1/16 notes (32 steps)",
    "16h": "1/16 half-swing (32 steps)", "16s": "1/16 swing (32 steps)",
}

BASS_SOUNDS = ["Deep medium kick, room", "Hard kick, gated reverb", "70s kick, room",
               "Tight 80s kick", "Loose old-fashioned soft kick", "Hard punchy kick",
               "TR909 'gulp' kick", "TR808 sustained-sine kick", "Deep kick with click, room"]
SNARE_SOUNDS = ["Rimshot, room", "Gated reverb snare", "Deep full snare", "Metal snare",
                "Brushes snare", "80s snare", "TR909 loose snare", "Soft cross-stick",
                "Old-fashioned ringy snare"]
HIHAT_SOUNDS = ["Metallic closed (shank)", "Breathy loose hihat", "Metallic closed (shank) 2",
                "Loose open hihat", "TR808 closed hihat", "Tight closed tick (tip)", "Shaker",
                "Ride cymbal", "Tambourine"]
PERC_BANKS = [("Soft shaker", "Loud shaker", "Breathy open hihat"),
              ("TR808 claps", "Ambient synth effect", "TR808 open hihat"),
              ("Tom low", "Tom mid", "Tambourine"),
              ("Triangle mute", "Triangle open", "Cowbell"),
              ("Conga high tone", "Conga high slap", "Conga low tone")]


# ----------------------------------------------------------------------------- messages

def _nibbles(n: int, limit: int) -> list[int]:
    if not 0 <= n < limit:
        raise ValueError(f"number must be 0-{limit - 1}, got {n}")
    return [n & 0x0F, (n >> 4) & 0x0F]  # LS 4 bits, MS 4 bits


def sysex(msg_id: int, payload: list[int] | None = None) -> mido.Message:
    return mido.Message("sysex", data=HEADER + [int(msg_id)] + list(payload or []))


def select_drumbeat(n: int) -> mido.Message:
    return sysex(MsgId.SELECT_DRUMBEAT, _nibbles(n, NUM_DRUMBEATS))


def select_preset(n: int) -> mido.Message:
    return sysex(MsgId.SELECT_PRESET, _nibbles(n, NUM_PRESETS))


def request_drumbeat(n: int) -> mido.Message:
    return sysex(MsgId.REQUEST_DRUMBEAT, _nibbles(n, NUM_DRUMBEATS))


def request_drumbeat_edit_buffer() -> mido.Message:
    return sysex(MsgId.REQUEST_DRUMBEAT_EDIT)


def request_system() -> mido.Message:
    return sysex(MsgId.REQUEST_SYSTEM)


def drumbeat_start(channel: int = 0) -> mido.Message:
    """Start the drumbeat via CC80 (default MIDI foot switch 'Start/stop drumbeat').

    For on/off foot-switch functions, CC data 127 = ON, 0 = OFF, 1-126 = toggle
    (manual ch. 4). Unlike MIDI Start, this works whatever the Sync setting is.
    """
    return mido.Message("control_change", channel=channel, control=CC_START_STOP, value=127)


def drumbeat_stop(channel: int = 0) -> mido.Message:
    return mido.Message("control_change", channel=channel, control=CC_START_STOP, value=0)


class ParamArea(IntEnum):
    PRESET_EDIT = 0b00
    DRUMBEAT_EDIT = 0b01
    SYSTEM = 0b10


SYS_GLOBAL_TEMPO = 2   # byte address in the System Parameters structure (30-250 BPM)
SYS_SYNC = 11          # 0 = --- (ignore clock), 1 = In, 2 = In-Out


def set_parameter(area: ParamArea, address: int, value: int) -> mido.Message:
    """Receive Single Parameter (ID 1). System params are saved immediately by the A3."""
    if not 0 <= address <= 0x7F or not 0 <= value <= 0xFF:
        raise ValueError("address must be 0-127 and value 0-255")
    return sysex(MsgId.RECEIVE_PARAMETER, [int(area), address, value & 0x0F, (value >> 4) & 0x0F])


def set_global_tempo(bpm: int) -> mido.Message:
    if not 30 <= bpm <= 250:
        raise ValueError(f"A3 tempo must be 30-250 BPM, got {bpm}")
    return set_parameter(ParamArea.SYSTEM, SYS_GLOBAL_TEMPO, bpm)


def select_drumbeat_pc(n: int, channel: int = 0) -> list[mido.Message]:
    """Alternative selection: CC32 bank (2 = drumbeats 0-99, 3 = 100-199) + Program Change."""
    if not 0 <= n < NUM_DRUMBEATS:
        raise ValueError(f"drumbeat must be 0-199, got {n}")
    bank = BANK_DRUMBEATS_0_99 if n < 100 else BANK_DRUMBEATS_100_199
    return [mido.Message("control_change", channel=channel, control=CC_BANK, value=bank),
            mido.Message("program_change", channel=channel, program=n % 100)]


IDENTITY_REQUEST = mido.Message("sysex", data=[0x7E, 0x00, 0x06, 0x01])  # dev 0: always answers


def parse_identity(msg: mido.Message) -> dict | None:
    """Return {'channel', 'version'} if ``msg`` is an A3 Identity Reply, else None."""
    d = list(msg.data) if msg.type == "sysex" else []
    if len(d) >= 14 and d[0] == 0x7E and d[2:4] == [0x06, 0x02] and d[4:7] == MANUFACTURER:
        family = d[7] | (d[8] << 7)
        member = d[9] | (d[10] << 7)
        version = "".join(chr(c) for c in d[11:14])
        # d[1] is documented as the MIDI channel, but firmware 3.03 answers 1 while its
        # System 'Channel' is ALL; treat it as an opaque device id. Use `a3 status`.
        return {"device_id": d[1], "family": family, "member": member,
                "version": version, "is_a3": family == 1 and member == 3}
    return None


def parse(msg: mido.Message) -> tuple[int, list[int]] | None:
    """Split an A3 SysEx into (message id, payload). None if not an A3 message."""
    if msg.type != "sysex":
        return None
    d = list(msg.data)
    if d[:4] != MANUFACTURER + [PRODUCT_ID] or len(d) < 5:
        return None
    if d[4] == MsgId.SAVE_COMPLETE:          # this one has no file-version byte
        return MsgId.SAVE_COMPLETE, []
    if d[4] != FILE_VERSION or len(d) < 6:
        return None
    return d[5], d[6:]


# ----------------------------------------------------------------------------- 7-bit packing

def unpack7(data: list[int]) -> bytes:
    """MIDI 7-bit data -> 8-bit memory. Each group: 1 byte of MS bits, then up to 7 bytes."""
    out = bytearray()
    for i in range(0, len(data), 8):
        msbs, chunk = data[i], data[i + 1:i + 8]
        for j, b in enumerate(chunk):
            out.append(b | (((msbs >> j) & 1) << 7))
    return bytes(out)


def pack7(raw: bytes) -> list[int]:
    out: list[int] = []
    for i in range(0, len(raw), 7):
        chunk = raw[i:i + 7]
        out.append(sum(((b >> 7) & 1) << j for j, b in enumerate(chunk)))
        out.extend(b & 0x7F for b in chunk)
    return out


# ----------------------------------------------------------------------------- drumbeat

DRUMBEAT_SIZE = 44
VOICES = ("bass", "snare", "hihat", "perc")


@dataclass
class Drumbeat:
    raw: bytes

    @classmethod
    def from_payload(cls, payload: list[int]) -> "Drumbeat":
        raw = unpack7(payload)
        if len(raw) < DRUMBEAT_SIZE:
            raise ValueError(f"drumbeat data too short: {len(raw)} bytes (expected {DRUMBEAT_SIZE})")
        return cls(raw[:DRUMBEAT_SIZE])

    # --- parameters
    volume = property(lambda self: self.raw[0])
    tempo = property(lambda self: self.raw[8])

    @property
    def fx_send(self) -> str:
        v = self.raw[1]
        if v < 100:
            return f"delay {v}"
        if v < 200:
            return f"guitar input {v - 100}"
        return f"reverb {v - 200}"

    @property
    def treble_dist(self) -> str:
        v = self.raw[2]
        if v == 0:
            return "---"
        if v <= 10:
            return f"t{(v - 1) * 10}"
        return f"d{(v - 11) * 10}"

    @property
    def timebase(self) -> str:
        v = self.raw[3]
        return TIMEBASES[v] if v < len(TIMEBASES) else f"?{v}"

    def sound(self, voice: str) -> tuple[int, int]:
        """(sound/bank 1-9, mix volume 0-9) from the BCD byte."""
        v = self.raw[4 + VOICES.index(voice)]
        return v // 10, v % 10

    def sound_name(self, voice: str) -> str:
        s, _ = self.sound(voice)
        if voice == "perc":
            bank = PERC_BANKS[s - 1] if 1 <= s <= len(PERC_BANKS) else ("?", "?", "?")
            return f"bank {s}: " + " / ".join(bank)
        names = {"bass": BASS_SOUNDS, "snare": SNARE_SOUNDS, "hihat": HIHAT_SOUNDS}[voice]
        return names[s - 1] if 1 <= s <= len(names) else f"? ({s})"

    # --- steps
    @property
    def steps(self) -> list[int]:
        return list(self.raw[12:44])

    def level(self, step: int, voice: str) -> int:
        return (self.raw[12 + step] >> (2 * VOICES.index(voice))) & 0x03

    def used_steps(self) -> list[int]:
        """Step indices actually played, depending on the timebase (manual ch. 3)."""
        tb = self.timebase
        if tb == "8n":                       # every alternate step skipped
            return list(range(0, 32, 2))
        if tb == "8t":                       # 4th step of each group of 4 skipped
            return [i for i in range(32) if i % 4 != 3]
        return list(range(32))

    def grid(self) -> list[str]:
        used = self.used_steps()
        per_beat = len(used) // 8            # 2 bars of 4 beats
        symbols = {"bass": ".-xX", "snare": ".-xX", "hihat": ".-xX", "perc": ".123"}
        def row(label: str, cells: list[str]) -> str:
            groups = ["".join(cells[i:i + per_beat]) for i in range(0, len(cells), per_beat)]
            return f"{label:<5} {' '.join(groups[:4])} | {' '.join(groups[4:])}"

        beat_labels = [str((i // per_beat) % 4 + 1) if i % per_beat == 0 else " "
                       for i in range(len(used))]
        rows = [row("", beat_labels)]
        for voice in VOICES:
            rows.append(row(voice, [symbols[voice][self.level(s, voice)] for s in used]))
        rows.append("      (.=off  -=soft  x=medium  X=loud;  perc 1/2/3 = sound in bank)")
        return rows

    def hit_count(self) -> dict[str, int]:
        used = self.used_steps()
        return {v: sum(1 for s in used if self.level(s, v)) for v in VOICES}

    def summary(self) -> list[str]:
        lines = [f"tempo {self.tempo} BPM | timebase {self.timebase} "
                 f"({TIMEBASE_HELP.get(self.timebase, 'future/unsupported')}) | "
                 f"volume {self.volume} | fx send {self.fx_send} | treble/dist {self.treble_dist}"]
        for v in VOICES:
            _, vol = self.sound(v)
            lines.append(f"  {v:<5} mix {vol}  {self.sound_name(v)}")
        return lines


# ----------------------------------------------------------------------------- system params

SYSTEM_FIELDS = [
    "active_preset", "active_drumbeat", "global_tempo", "master_volume", None,
    "preset_sets_drumbeat", "noise_gate", "balance", "tempo_source", "direct_amp",
    "channel", "sync", "prog_change_bank", "midi_dump_mode", "pedal1_source",
    "pedal2_source", "midi_drums",
]
SYNC_NAMES = {0: "--- (ignore clock)", 1: "In", 2: "In-Out"}
TEMPO_SOURCE_NAMES = {0: "system tempo", 1: "drumbeat tempo", 2: "preset tempo"}
PC_BANK_NAMES = {0: "presets 0-99", 1: "presets 100-199", 2: "drumbeats 0-99",
                 3: "drumbeats 100-199", 4: "none"}


def decode_system(payload: list[int]) -> dict:
    """Decode System Parameters (ID 15). Only fields present in the reply are returned.

    The implementation doc says '14 bytes in 16 MIDI bytes' but lists ~46 fields; we
    decode whatever length the device actually sends.
    """
    raw = unpack7(payload)
    out = {"_raw": raw}
    for i, name in enumerate(SYSTEM_FIELDS):
        if name and i < len(raw):
            out[name] = raw[i]
    return out


def describe_system(sp: dict) -> list[str]:
    lines = []
    fmt = {
        "channel": lambda v: "ALL (omni)" if v == 0 else str(v),
        "sync": lambda v: SYNC_NAMES.get(v, str(v)),
        "tempo_source": lambda v: TEMPO_SOURCE_NAMES.get(v, str(v)),
        "prog_change_bank": lambda v: PC_BANK_NAMES.get(v, str(v)),
        "midi_drums": lambda v: "ON" if v else "OFF",
        "preset_sets_drumbeat": lambda v: "ON" if v else "OFF",
    }
    for k, v in sp.items():
        if k.startswith("_"):
            continue
        lines.append(f"  {k:<22} {fmt.get(k, str)(v)}")
    lines.append(f"  ({len(sp['_raw'])} bytes received)")
    return lines
