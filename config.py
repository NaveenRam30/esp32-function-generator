"""config.py - default limits, hardware description and UI colours.

Everything that a hardware builder might want to tweak lives here, so the
rest of the code never contains "magic numbers".
"""
from dataclasses import dataclass

APP_TITLE = "ESP32 FUNCTION GENERATOR"

# --------------------------------------------------------------------------
# Serial link
# --------------------------------------------------------------------------
DEFAULT_BAUD = 115200
BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
ACK_TIMEOUT_S = 2.0         # how long we wait for OK/ERROR/... after a command
STATUS_POLL_MS = 1000       # periodic STATUS request while connected
PORT_REFRESH_MS = 2000      # re-scan serial ports while disconnected
LIVE_DEBOUNCE_MS = 250      # delay before "live update" sends CONFIG
CONNECT_SETTLE_S = 1.5      # ESP32 boards often reset when the port opens

# --------------------------------------------------------------------------
# Generator limits (what the GUI accepts; the ESP32 firmware has the last word)
# --------------------------------------------------------------------------
WAVEFORMS = ["Sine", "Square", "Triangle", "Sawtooth", "Pulse"]
DUTY_WAVEFORMS = ("Square", "Pulse")   # waveforms where duty cycle applies

FREQ_MIN_HZ = 1.0
FREQ_MAX_HZ = 50_000.0     # practical limit for a timer-driven 8-bit DAC output
VPP_MIN = 0.0
VPP_MAX = 5.0              # GUI range; > 3.3 V needs an external output stage
PHASE_MIN = 0.0
PHASE_MAX = 360.0
DUTY_MIN = 1.0
DUTY_MAX = 99.0
SWEEP_TIME_MIN_S = 0.1
SWEEP_TIME_MAX_S = 3600.0

# --------------------------------------------------------------------------
# Hardware description
# --------------------------------------------------------------------------
DAC_BITS = 8                # ESP32 internal DAC resolution
DAC_DIRECT_MAX_V = 3.3

# Output configuration -> (minimum voltage, maximum voltage) that can be
# produced. "External stage" is an example: adjust it to your real circuit.
OUTPUT_MODES = {
    "Direct ESP32 DAC (0 to 3.3 V)": (0.0, DAC_DIRECT_MAX_V),
    "External output stage (-5 to +5 V)": (-5.0, 5.0),
}
DEFAULT_OUTPUT_MODE = "Direct ESP32 DAC (0 to 3.3 V)"

HW_LIMIT_MESSAGE = ("ESP32 DAC output is approximately 0\u20133.3 V. "
                    "Higher output voltages require an external analog "
                    "output stage.")

# --------------------------------------------------------------------------
# Presets: name -> (waveform, frequency in Hz)
# --------------------------------------------------------------------------
PRESETS = {
    "1 kHz Sine": ("Sine", 1000.0),
    "1 kHz Square": ("Square", 1000.0),
    "1 kHz Triangle": ("Triangle", 1000.0),
    "100 Hz Sine": ("Sine", 100.0),
    "10 kHz Sine": ("Sine", 10000.0),
}

# --------------------------------------------------------------------------
# Colours (dark laboratory instrument look)
# --------------------------------------------------------------------------
COLORS = {
    "bg": "#0f1216",
    "header": "#171c23",
    "panel": "#1a2027",
    "panel2": "#232b35",
    "hover": "#2f3a47",
    "field": "#0d1014",
    "border": "#2c3540",
    "fg": "#e3e9ef",
    "dim": "#8794a3",
    "accent": "#33c9ff",
    "ok": "#38d27a",
    "warn": "#ffb02e",
    "err": "#ff5c5c",
    "bad_bg": "#3a1e1e",
    "trace": "#39e58c",
    "plot_bg": "#0a0d10",
    "grid": "#26303a",
}


@dataclass
class GeneratorSettings:
    """The complete user-controlled configuration of the generator."""
    wave: str = "Sine"
    freq_hz: float = 1000.0
    vpp: float = 2.0            # peak-to-peak amplitude, the main parameter
    offset: float = 1.0         # DC level at the CENTRE of the waveform
    phase_deg: float = 0.0
    duty_pct: float = 50.0
