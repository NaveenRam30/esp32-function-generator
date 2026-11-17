"""calculations.py - voltage maths (Vpp, peak, RMS, limits, warnings).

Conventions used throughout the application
-------------------------------------------
* Vpp     : peak-to-peak amplitude = (max level - min level). This is the
            main user-controlled amplitude parameter.
* Peak    : Vpp / 2, measured from the waveform centre.
* Offset  : DC level at the centre of the waveform, so
            min = offset - Vpp/2 and max = offset + Vpp/2.
            Example: 2 Vpp with 1 V offset -> 0 V ... 2 V.
* RMS(AC) : RMS of the waveform with its own mean removed.
* RMS(tot): RMS including the DC component (what a true-RMS meter reads on DC
            coupling).
"""
import math

from config import GeneratorSettings


def format_frequency(hz: float) -> str:
    """Human readable frequency, e.g. 1500 -> '1.5 kHz'."""
    if hz >= 1000.0:
        return f"{hz / 1000.0:.4g} kHz"
    return f"{hz:.4g} Hz"


def peak_voltage(vpp: float) -> float:
    return vpp / 2.0


def output_limits(vpp: float, offset: float):
    """Return (minimum, maximum) output voltage."""
    return offset - vpp / 2.0, offset + vpp / 2.0


def _duty(duty_pct: float) -> float:
    return min(max(duty_pct / 100.0, 0.0), 1.0)


def rms_ac(wave: str, vpp: float, duty_pct: float = 50.0) -> float:
    """RMS of the AC part of the waveform (mean removed)."""
    w = wave.upper()
    if w == "SINE":
        return vpp / (2.0 * math.sqrt(2.0))
    if w in ("SQUARE", "PULSE"):
        d = _duty(duty_pct)                    # rectangular wave between two levels
        return vpp * math.sqrt(d * (1.0 - d))  # 50 % duty -> Vpp / 2
    if w in ("TRIANGLE", "SAWTOOTH"):
        return vpp / (2.0 * math.sqrt(3.0))
    raise ValueError(f"Unknown waveform: {wave}")


def mean_level(wave: str, vpp: float, offset: float, duty_pct: float = 50.0) -> float:
    """DC (average) level of the waveform."""
    if wave.upper() in ("SQUARE", "PULSE"):
        return offset + vpp * (_duty(duty_pct) - 0.5)
    return offset


def rms_total(wave: str, vpp: float, offset: float, duty_pct: float = 50.0) -> float:
    """RMS including the DC component."""
    ac = rms_ac(wave, vpp, duty_pct)
    dc = mean_level(wave, vpp, offset, duty_pct)
    return math.sqrt(ac * ac + dc * dc)


def hardware_warnings(s: GeneratorSettings, hw_min: float, hw_max: float):
    """Return a list of human readable warnings (empty list = all fine).

    Requested values are NEVER silently clipped: the GUI shows these messages
    and asks for confirmation before sending an impossible configuration.
    """
    lo, hi = output_limits(s.vpp, s.offset)
    span = hw_max - hw_min
    warnings = []
    if s.vpp > span + 1e-9:
        warnings.append(
            f"{s.vpp:.2f} Vpp exceeds the {span:.2f} V span that the selected "
            f"output configuration can generate directly.")
    if lo < hw_min - 1e-9 or hi > hw_max + 1e-9:
        warnings.append(
            f"Requested output {lo:.2f} V to {hi:.2f} V is outside the hardware "
            f"range {hw_min:.2f} V to {hw_max:.2f} V and cannot be generated "
            f"directly (it would clip).")
    if warnings and hw_max <= 3.3 + 1e-9:
        warnings.append(
            "Voltages above approximately 3.3 V require an external analog "
            "output stage.")
    return warnings
