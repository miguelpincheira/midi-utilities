# pyMidi — MIDI test & control toolkit

Command-line tools to test, debug and drive the MIDI ports of the sound board
and the external hardware connected to it. Built on [mido](https://mido.readthedocs.io)
+ python-rtmidi (CoreMIDI on macOS).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Default port

Every command uses the **Clarett** MIDI ports unless `--port` is given
(`monitor` and `panic` also accept `--all`). Change the default in
[midi_tools/config.py](midi_tools/config.py) or per shell with `export PYMIDI_PORT="name"`.

## Usage

```bash
python -m midi_tools list                      # show input/output ports with indexes
python -m midi_tools monitor                   # watch the Clarett input (Ctrl+C to stop)
python -m midi_tools monitor --all             # watch every input
python -m midi_tools monitor -p clarett -c 10 --raw
python -m midi_tools monitor --virtual Spy     # create a virtual port other apps can send to

python -m midi_tools send -p clarett note C4                 # 0.5 s note on ch 1
python -m midi_tools send -p clarett -c 10 note 36 38 -d 1   # chord on ch 10
python -m midi_tools send -p clarett cc 7 100
python -m midi_tools send -p clarett pc 4 --bank 1
python -m midi_tools send -p clarett pitch -2000
python -m midi_tools send -p clarett sysex "F0 7E 7F 06 01 F7"   # Identity Request
python -m midi_tools send -p clarett raw "B0 7B 00"

python -m midi_tools panic                     # Clarett, all channels
python -m midi_tools panic --all               # every output
python -m midi_tools panic -p clarett --hard   # + note-off for every note
```

Conventions:

- `--port` accepts an index from `list`, the exact name, or any unique substring (case-insensitive).
- Channels are **1–16** (as on hardware panels).
- Note names use **C4 = 60** (some manufacturers, e.g. Yamaha, call 60 "C3").
- Program numbers are sent as-is (0–127); many devices display them as 1–128.
- The monitor hides `clock` / `active_sensing` by default (`--show-clock` to see them).

## AdrenaLinn III (A3)

Wiring: Clarett MIDI OUT → A3 MIDI IN (required), A3 MIDI OUT → Clarett MIDI IN
(needed for identify/status/dumps). Protocol per `docs/hardware/Adrenalinn_iii_midi_implementation*.pdf`.

```bash
python -m midi_tools a3 identify               # does the A3 answer? (firmware version)
python -m midi_tools a3 status                 # system params: sync, tempo source, MIDI drums...
python -m midi_tools a3 show 0-9               # dump drumbeats and print their step grids
python -m midi_tools a3 show 12 --save b12.syx # ...and save the SysEx dump
python -m midi_tools a3 play 0-9               # audition: select, play 4 bars, stop, next
python -m midi_tools a3 play 0-199 -i          # interactive: ok / b=bad / r=replay / q=quit
python -m midi_tools a3 play 20 --bars 8 --bpm 120
python -m midi_tools a3 drums                  # trigger each voice (notes 36/38/40/41/43/45)
python -m midi_tools a3 transport start|stop|continue|select N
.venv/bin/python a3_rundown.py                # scripted rundown: presets 7/21, tempo 150/120
.venv/bin/python a3_fix_midi.py               # DAW sync broken? set A3 MIDI Sync = In and verify
.venv/bin/python a3_fix_midi.py --check       # ...or just report
```

Drumbeat test notes:

- `play` reads the A3 system settings first. If **MIDI Sync = In**, it drives the A3 with its own
  MIDI clock (tempo = drumbeat tempo or `--bpm`). If **Sync = ---** it only sends Start/Stop and
  times the run from the A3's own tempo source (global tempo or drumbeat tempo).
- Start/stop uses **CC80** (A3 default MIDI foot switch "Start/stop drumbeat", 127 = start,
  0 = stop). The A3 (fw 3.03) ignores MIDI Start/Stop while Sync is `---`; `--realtime` sends them anyway.
- Selection uses SysEx *Select Drumbeat* (`--select pc` = CC32 bank + Program Change instead).
- Afterwards the previously active drumbeat is restored (`--keep` to stay on the last one).
- `drums` needs System → *MIDI Drums* = ON. Bass/snare/hihat are played in all 3 velocity zones.
- Nothing here writes to the A3's flash (no drumbeat/preset upload, no factory init).

## Layout

```
midi_tools/
  __main__.py     CLI entry point (subcommands)
  common.py       port lookup, note/hex parsing, message formatting
  list_ports.py   `list`
  monitor.py      `monitor`
  send.py         `send`
  panic.py        `panic`
  a3.py           `a3` (AdrenaLinn III commands)
  config.py       default port
  devices/
    adrenalinn3.py  A3 SysEx, 7-bit packing, drumbeat/system decoders
docs/hardware/    manuals / MIDI implementation charts of the connected gear
```
