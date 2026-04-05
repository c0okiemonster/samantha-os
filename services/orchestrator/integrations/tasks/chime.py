"""Generate a soft chime WAV file for overlay-card notifications.
Called once on orchestrator startup. Idempotent."""
from __future__ import annotations

import os
import wave

import numpy as np


SAMPLE_RATE = 24000
DURATION_S = 0.8
PEAK_DBFS = -18.0


def ensure_chime_exists(path: str) -> None:
    """Write chime.wav at `path` if it does not already exist."""
    if os.path.exists(path):
        return

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    t = np.linspace(0, DURATION_S, int(SAMPLE_RATE * DURATION_S), endpoint=False)

    # Two partials: C5 (523.25 Hz) and E5 (659.25 Hz), 3:1 amplitude
    fundamental = np.sin(2 * np.pi * 523.25 * t)
    third = np.sin(2 * np.pi * 659.25 * t)
    tone = 0.75 * fundamental + 0.25 * third

    decay = np.exp(-3.5 * t / DURATION_S)
    attack_samples = int(0.005 * SAMPLE_RATE)
    attack = np.ones_like(t)
    attack[:attack_samples] = np.linspace(0, 1, attack_samples)

    signal = tone * decay * attack

    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak
    target_amplitude = 10 ** (PEAK_DBFS / 20.0)
    signal = signal * target_amplitude

    pcm16 = np.int16(signal * 32767)

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm16.tobytes())
