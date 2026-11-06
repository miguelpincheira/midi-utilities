"""Background MIDI clock (24 ppqn) whose tempo can be changed while running."""
from __future__ import annotations

import threading
import time

import mido


class MidiClock:
    """Sends MIDI Timing Clock from a background thread.

    ``send`` must be thread-safe; use :class:`LockedSender` around a mido output
    if other threads send on the same port.
    """

    def __init__(self, send, bpm: float):
        self._send = send
        self.bpm = bpm
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="midi-clock", daemon=True)
        self.ticks = 0

    def start(self) -> "MidiClock":
        self._thread.start()
        return self

    def set_bpm(self, bpm: float) -> None:
        self.bpm = bpm  # picked up at the next tick

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        tick = mido.Message("clock")
        next_t = time.perf_counter()
        while not self._stop.is_set():
            self._send(tick)
            self.ticks += 1
            next_t += 60.0 / (self.bpm * 24)
            while True:  # coarse sleep, then spin the last ~1.5 ms
                remaining = next_t - time.perf_counter()
                if remaining <= 0 or self._stop.is_set():
                    break
                time.sleep(remaining - 0.0015 if remaining > 0.002 else 0)


class LockedSender:
    """Serialises ``send`` calls on a mido output from several threads."""

    def __init__(self, out):
        self._out = out
        self._lock = threading.Lock()

    def __call__(self, msg: mido.Message) -> None:
        with self._lock:
            self._out.send(msg)
