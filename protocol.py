"""protocol.py - build commands for the ESP32 and parse its replies.

The protocol is line based ASCII, one message per line, terminated by '\\n'.

PC -> ESP32
-----------
    CONFIG,WAVE=SINE,FREQ=1000,VPP=2.0,OFFSET=1.0,PHASE=90,DUTY=50
    SET,WAVE,SINE | SET,FREQ,1000 | SET,VPP,2.0 | SET,OFFSET,1.0 |
    SET,PHASE,90 | SET,DUTY,50          (alternative to CONFIG)
    START | STOP | PAUSE | RESUME | RESET | STATUS
    SWEEP,CONFIG,F1=100,F2=10000,T=5.0,MODE=LOG      (MODE = LIN or LOG)
    SWEEP,START | SWEEP,STOP

ESP32 -> PC
-----------
    OK | OK,<text> | ERROR,<code or text> | READY | RUNNING | STOPPED | PAUSED
    STATUS,WAVE=SINE,FREQ=1000,VPP=2.0,OFFSET=1.0,PHASE=90,DUTY=50,
           STATE=RUNNING,FS=100000,SAMPLES=256,FW=1.0.0,SWEEP=OFF
    MEAS,FREQ=999.8,DAC=128,FS=100000        (optional, sent whenever wanted)
"""
from dataclasses import dataclass, field

from config import GeneratorSettings

# Reply kinds that can acknowledge a command
_ACK_BY_VERB = {
    "STATUS": {"STATUS", "ERROR"},
    "START": {"OK", "RUNNING", "ERROR"},
    "STOP": {"OK", "STOPPED", "ERROR"},
    "PAUSE": {"OK", "PAUSED", "ERROR"},
    "RESUME": {"OK", "RUNNING", "ERROR"},
    "RESET": {"OK", "READY", "ERROR"},
}
_DEFAULT_ACK = {"OK", "ERROR"}          # CONFIG, SET, SWEEP,...

KNOWN_KINDS = {"OK", "ERROR", "READY", "RUNNING", "STOPPED", "PAUSED",
               "STATUS", "MEAS"}

_ERROR_TEXT = {
    "INVALID_COMMAND": "unknown or malformed command",
    "UNKNOWN_COMMAND": "unknown or malformed command",
    "INVALID_PARAM": "invalid parameter",
    "INVALID_PARAMETER": "invalid parameter",
    "FREQ_RANGE": "frequency out of range",
    "VPP_RANGE": "amplitude out of range",
    "OFFSET_RANGE": "DC offset out of range",
    "PHASE_RANGE": "phase out of range",
    "DUTY_RANGE": "duty cycle out of range",
    "BUSY": "ESP32 is busy",
}


@dataclass
class Response:
    kind: str                       # OK, ERROR, STATUS, MEAS, UNKNOWN, ...
    message: str = ""               # text after "OK," / "ERROR,"
    fields: dict = field(default_factory=dict)   # KEY=VALUE pairs (upper-case keys)
    raw: str = ""


def _num(value: float, decimals: int = 6) -> str:
    """Compact number formatting: 1000.0 -> '1000', 2.5 -> '2.5'."""
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text if text else "0"


# ---------------------------------------------------------------- commands
def cmd_config(s: GeneratorSettings) -> str:
    return (f"CONFIG,WAVE={s.wave.upper()},FREQ={_num(s.freq_hz)},"
            f"VPP={_num(s.vpp, 3)},OFFSET={_num(s.offset, 3)},"
            f"PHASE={_num(s.phase_deg, 2)},DUTY={_num(s.duty_pct, 2)}")


def cmd_set_sequence(s: GeneratorSettings) -> list:
    """Same information as cmd_config() but as individual SET commands."""
    return [f"SET,WAVE,{s.wave.upper()}", f"SET,FREQ,{_num(s.freq_hz)}",
            f"SET,VPP,{_num(s.vpp, 3)}", f"SET,OFFSET,{_num(s.offset, 3)}",
            f"SET,PHASE,{_num(s.phase_deg, 2)}", f"SET,DUTY,{_num(s.duty_pct, 2)}"]


def cmd_sweep_config(f1_hz: float, f2_hz: float, duration_s: float, log: bool) -> str:
    return (f"SWEEP,CONFIG,F1={_num(f1_hz)},F2={_num(f2_hz)},"
            f"T={_num(duration_s, 3)},MODE={'LOG' if log else 'LIN'}")


CMD_START = "START"
CMD_STOP = "STOP"
CMD_PAUSE = "PAUSE"
CMD_RESUME = "RESUME"
CMD_RESET = "RESET"
CMD_STATUS = "STATUS"
CMD_SWEEP_START = "SWEEP,START"
CMD_SWEEP_STOP = "SWEEP,STOP"


def ack_kinds(command: str) -> set:
    """Which reply kinds count as the answer to `command`."""
    verb = command.split(",", 1)[0].strip().upper()
    return _ACK_BY_VERB.get(verb, _DEFAULT_ACK)


# ---------------------------------------------------------------- replies
def parse_line(line: str) -> Response:
    """Parse one line received from the ESP32 (never raises)."""
    raw = line.strip()
    if not raw:
        return Response("UNKNOWN", raw=raw)
    parts = raw.split(",")
    kind = parts[0].strip().upper()
    if kind not in KNOWN_KINDS:
        return Response("UNKNOWN", message=raw, raw=raw)
    if kind in ("STATUS", "MEAS"):
        fields = {}
        for item in parts[1:]:
            if "=" in item:
                key, _, value = item.partition("=")
                fields[key.strip().upper()] = value.strip()
        return Response(kind, fields=fields, raw=raw)
    return Response(kind, message=",".join(parts[1:]).strip(), raw=raw)


def describe_error(message: str) -> str:
    """Translate an ESP32 error code into friendly text (falls back to raw)."""
    key = message.strip().upper().replace(" ", "_")
    return _ERROR_TEXT.get(key, message.strip() or "unspecified error")
