"""waveform.py - NumPy waveforms for the on-screen PREVIEW only.

The real signal is produced by the ESP32. This module just draws what the
configuration is expected to look like.
"""
import numpy as np

from config import GeneratorSettings


def shape(wave: str, phase_cycles, duty: float):
    """Normalised waveform (-1 ... +1) for a phase given in cycles.

    All shapes start at 0 (sine-like zero crossing) for 0 degrees phase,
    except square/pulse which start at their rising edge.
    """
    p = np.mod(phase_cycles, 1.0)
    w = wave.upper()
    if w == "SINE":
        return np.sin(2.0 * np.pi * p)
    if w in ("SQUARE", "PULSE"):
        return np.where(p < duty, 1.0, -1.0)
    if w == "TRIANGLE":
        return 1.0 - 4.0 * np.abs(np.mod(p + 0.25, 1.0) - 0.5)
    if w == "SAWTOOTH":
        return 2.0 * np.mod(p + 0.5, 1.0) - 1.0
    raise ValueError(f"Unknown waveform: {wave}")


def voltage(s: GeneratorSettings, t):
    """Output voltage of configuration `s` at times `t` (seconds)."""
    phase = s.freq_hz * np.asarray(t) + s.phase_deg / 360.0
    return s.offset + (s.vpp / 2.0) * shape(s.wave, phase, s.duty_pct / 100.0)


def preview(s: GeneratorSettings, cycles: int = 4, points_per_cycle: int = 400):
    """Return (t_seconds, volts, time_unit_name, unit_scale).

    The time window is always `cycles` periods long, so several cycles stay
    visible whatever the frequency is (1 Hz ... 50 kHz).
    """
    span = cycles / s.freq_hz
    t = np.linspace(0.0, span, cycles * points_per_cycle + 1)
    v = voltage(s, t)
    if span < 1e-3:
        unit, scale = "\u00b5s", 1e6
    elif span < 1.0:
        unit, scale = "ms", 1e3
    else:
        unit, scale = "s", 1.0
    return t, v, unit, scale
