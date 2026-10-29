# ESP32 Function Generator – PC control GUI

Python/Tkinter front-end for an ESP32 that generates the real waveform.
The PC only **configures**, **previews**, **sends commands** and **shows what the ESP32 reports**. Nothing is simulated in Python.

## Install and run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Tkinter ships with Python on Windows/macOS. On Debian/Ubuntu: `sudo apt install python3-tk`.
On Linux you may need serial permission: `sudo usermod -aG dialout $USER` (then log out/in).
The window is designed for about 1400 x 990 px.

## Files

| File | Purpose |
|---|---|
| `main.py` | starts the app |
| `gui.py` | Tkinter GUI, input validation, event handling |
| `serial_manager.py` | worker thread, command queue, ACK/timeout handling |
| `protocol.py` | builds commands, parses ESP32 replies |
| `waveform.py` | NumPy preview waveforms |
| `calculations.py` | Vpp / peak / RMS / min / max / hardware warnings |
| `config.py` | limits, presets, output configurations, colours |

## Conventions

* **Vpp** is the controlled amplitude. **Peak** = Vpp / 2.
* **DC offset** is the level at the *centre* of the waveform: `min = offset - Vpp/2`, `max = offset + Vpp/2` (2 Vpp + 1 V offset -> 0 V … 2 V).
* **RMS (AC)**: sine Vpp/(2√2), triangle/sawtooth Vpp/(2√3), square/pulse Vpp·√(D(1−D)). **RMS (total)** adds the DC component.
* Values are never silently clipped. Out-of-range entries turn red and are not applied; requests beyond the selected hardware range show a warning and a confirmation dialog before sending.
* Hardware ranges are set in `config.OUTPUT_MODES`. Adjust the "external stage" entry to match your real output circuit.
* Frequency range is `config.FREQ_MIN_HZ … FREQ_MAX_HZ` (1 Hz – 50 kHz). Your firmware decides what it can really do and should answer `ERROR,FREQ_RANGE` otherwise.

## Serial protocol (115200 baud, ASCII, one line per message, `\n` terminated)

### PC -> ESP32

| Command | Meaning |
|---|---|
| `CONFIG,WAVE=SINE,FREQ=1000,VPP=2,OFFSET=1,PHASE=90,DUTY=50` | full configuration (used by the GUI) |
| `SET,WAVE,SINE` / `SET,FREQ,1000` / `SET,VPP,2.0` / `SET,OFFSET,1.0` / `SET,PHASE,90` / `SET,DUTY,50` | single parameters (`protocol.cmd_set_sequence`) |
| `START` / `STOP` | start / stop the output |
| `PAUSE` / `RESUME` | hold / continue the output |
| `RESET` | restore defaults (GUI resets its controls too) |
| `STATUS` | request status (also polled once per second) |
| `SWEEP,CONFIG,F1=100,F2=10000,T=5,MODE=LOG` | sweep setup, `MODE` = `LIN` or `LOG`, `T` in seconds |
| `SWEEP,START` / `SWEEP,STOP` | run / stop the sweep |

`WAVE` is one of `SINE, SQUARE, TRIANGLE, SAWTOOTH, PULSE`. Units: Hz, V, degrees, percent.

### ESP32 -> PC

| Reply | Used as answer to |
|---|---|
| `OK` or `OK,<text>` | CONFIG, SET, SWEEP, START, STOP, PAUSE, RESUME, RESET |
| `ERROR,<code or text>` | any command. Codes understood: `INVALID_COMMAND`, `INVALID_PARAM`, `FREQ_RANGE`, `VPP_RANGE`, `OFFSET_RANGE`, `PHASE_RANGE`, `DUTY_RANGE`, `BUSY` |
| `RUNNING` / `STOPPED` / `PAUSED` | START(RESUME) / STOP / PAUSE (may also be sent unsolicited) |
| `READY` | after RESET or on boot |
| `STATUS,WAVE=SINE,FREQ=1000,VPP=2.0,OFFSET=1.0,PHASE=90,DUTY=50,STATE=RUNNING,FS=100000,SAMPLES=256,FW=1.0.0,SWEEP=OFF` | STATUS. Every key is optional |
| `MEAS,FREQ=999.8,DAC=128,FS=100000` | optional, may be sent at any time. Shown in the "Measured" column (`DAC` is the raw 8-bit value) |

Each command waits for its reply (2 s timeout, `config.ACK_TIMEOUT_S`). Lines the GUI does not recognise (e.g. ESP32 boot messages) are shown in the log only.

### Example session

```
PC    -> CONFIG,WAVE=SINE,FREQ=1000,VPP=2,OFFSET=1,PHASE=90,DUTY=50
ESP32 -> OK
PC    -> START
ESP32 -> RUNNING
PC    -> STATUS
ESP32 -> STATUS,WAVE=SINE,FREQ=1000,VPP=2.0,PHASE=90,STATE=RUNNING,FS=100000,SAMPLES=256,FW=1.0.0
ESP32 -> MEAS,FREQ=1000.2,DAC=128,FS=100000
PC    -> CONFIG,WAVE=SINE,FREQ=99999999,VPP=2,OFFSET=1,PHASE=0,DUTY=50
ESP32 -> ERROR,FREQ_RANGE
PC    -> STOP
ESP32 -> STOPPED
```

## Notes

* Opening the port resets many ESP32 boards (DTR/RTS). The GUI waits 1.5 s before its first STATUS request.
* "Live update" re-sends `CONFIG` while running (250 ms debounce); it is skipped when a value exceeds the hardware range.
* Pulse defaults to 10 % duty when selected; square keeps 50 %.
* Tested here: calculations, protocol parsing, preview maths and a headless GUI smoke test with fake ESP32 replies. It has not been tested against real firmware.
