
# ESP32 Function Generator — Firmware and Python GUI

An ESP32-based function generator with a Python/Tkinter desktop application for waveform configuration, visualization, and serial control.

The ESP32 generates the physical waveform, while the Python GUI configures the output, previews waveform parameters, sends commands, and displays device responses.

**Note:** The waveform displayed in the GUI is a software-generated preview, not a physical measurement of the ESP32 output.

## 1. Project Components

The project consists of two main components:

### ESP32 Firmware

- Generates waveforms using the ESP32's internal DAC.
- Supports serial configuration and output control.
- Uses GPIO25 (DAC1) for analog waveform output.
- Supports Arduino-ESP32 core 2.x/3.x through conditional compilation.
- Firmware version: 1.0.0.

### Python Desktop GUI

- Developed using Python and Tkinter.
- Provides waveform configuration and visualization.
- Communicates with the ESP32 over USB serial.
- Supports output control, frequency sweeps, presets, and monitoring.
- Includes an enlarged waveform preview and redesigned workspace.

## 2. Repository Structure

```text
esp32-function-generator/
|
|-- esp32_function_generator/
|   `-- esp32_function_generator.ino
|
|-- main.py
|-- gui.py
|-- calculations.py
|-- config.py
|-- protocol.py
|-- serial_manager.py
|-- waveform.py
|-- requirements.txt
|
|-- docs/
|   `-- HARDWARE_CHECKLIST.md
|
|-- README.md
|-- CHANGELOG.md
|-- CONTRIBUTORS.md
|-- BRANCH_GUIDE.md
|-- VERSION
|-- .gitignore
|-- .gitattributes
`-- .github/
```

The firmware and GUI also retain separate development branches.

## 3. Hardware Requirements

- Classic ESP32 development board with an internal DAC
- USB cable for programming and serial communication
- Computer running Python
- Arduino IDE with ESP32 board support
- Oscilloscope or DSO for physical waveform verification

The ESP32 firmware targets a classic ESP32 supporting DAC1 on GPIO25.

## 4. Firmware Installation

1. Install Arduino IDE.
2. Install the Espressif ESP32 board package.
3. Open:

   `esp32_function_generator/esp32_function_generator.ino`

4. Select the appropriate ESP32 board and serial port.
5. Verify the installed Arduino-ESP32 core version.
6. Compile and upload the firmware.

The firmware contains conditional compilation for Arduino-ESP32 core 2.x and 3.x.

### Firmware Configuration

| Parameter | Value |
|---|---|
| Controller | Classic ESP32 |
| DAC output | GPIO25 / DAC1 |
| Serial baud rate | 115200 |
| Serial format | ASCII |
| Message termination | Newline |
| Internal firmware version | 1.0.0 |

The actual board, core version, successful upload, and analog output should be verified on hardware.

## 5. Python GUI Installation

Create a Python virtual environment:

```bash
python -m venv .venv
```

Activate it.

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the GUI:

```bash
python main.py
```

Tkinter is generally included with Python on Windows and macOS.

For Debian/Ubuntu:

```bash
sudo apt install python3-tk
```

Linux users may require serial-port permissions:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in after changing group membership.

## 6. Python Source Files

| File | Purpose |
|---|---|
| `main.py` | Starts the application |
| `gui.py` | Tkinter interface, input validation, and event handling |
| `serial_manager.py` | Serial worker thread, command queue, ACK and timeout handling |
| `protocol.py` | Command generation and ESP32 response parsing |
| `waveform.py` | NumPy-based waveform previews |
| `calculations.py` | Peak, Vpp, RMS, minimum/maximum, and hardware-limit calculations |
| `config.py` | Operating limits, presets, output modes, and interface settings |

## 7. Supported Waveforms

The application supports:

- Sine
- Square
- Triangle
- Sawtooth
- Pulse

Configurable parameters include:

- Frequency
- Peak-to-peak voltage
- DC offset
- Phase
- Duty cycle
- Output configuration

The GUI configuration range is 1 Hz to 50 kHz. The actual supported range depends on the firmware and hardware.

## 8. GUI Features

### Waveform Preview

The updated GUI includes:

- Enlarged waveform visualization
- Thicker waveform traces and readable axes
- Large frequency and amplitude readouts
- Resizable preview workspace
- Focus preview mode
- Fullscreen support using F11
- Escape using Esc
- Preview selection of 2, 4, or 8 cycles

### Display Scaling

Two preview modes are available:

- **Fit waveform:** Scales the displayed waveform to use more of the available vertical space.
- **Hardware range:** Displays the selected hardware voltage range.

These settings affect only visualization, not the physical output.

### Settings and Monitoring

The interface provides:

- Signal configuration
- Frequency sweep configuration
- Output-stage selection
- Presets
- Input validation
- Hardware-limit warnings
- Serial monitoring
- Device status
- Communication logs

The separate details/log window contains Output details, Device status, Monitoring, and Serial log tabs.

### Output Controls

Supported operations include:

- Start
- Stop
- Pause
- Resume
- Reset
- Live parameter updates
- Frequency sweep start/stop

The GUI V2 redesign preserves the original communication protocol and control behavior.

## 9. Waveform Calculations

### Peak-to-Peak Voltage

Peak-to-peak voltage is the controlled amplitude.

```text
Peak = Vpp / 2
```

### DC Offset

The DC offset defines the center of the waveform.

```text
Minimum = Offset - Vpp/2
Maximum = Offset + Vpp/2
```

Example:

For 2 Vpp and 1 V offset:

```text
Minimum = 0 V
Maximum = 2 V
```

### RMS Voltage

For zero-mean AC waveforms:

Sine:

```text
Vrms = Vpp / (2 * sqrt(2))
```

Triangle/Sawtooth:

```text
Vrms = Vpp / (2 * sqrt(3))
```

Square/Pulse:

```text
Vrms = Vpp * sqrt(D * (1-D))
```

Here, D is the duty-cycle fraction.

Total RMS also includes the DC component.

### Hardware Limits

The GUI does not silently clip invalid values.

- Out-of-range inputs are highlighted.
- Invalid parameters are not applied.
- Hardware-range violations generate warnings.
- User confirmation is required before sending requests beyond the selected output range.

Hardware configurations are defined in `config.OUTPUT_MODES`.

## 10. Serial Communication Protocol

The ESP32 and Python GUI communicate using:

| Parameter | Configuration |
|---|---|
| Interface | USB serial |
| Baud rate | 115200 |
| Encoding | ASCII |
| Termination | Newline (`\n`) |
| Command timeout | 2 seconds |
| Status polling | Once per second |

### PC to ESP32 Commands

| Command | Function |
|---|---|
| `CONFIG,WAVE=SINE,FREQ=1000,VPP=2,OFFSET=1,PHASE=90,DUTY=50` | Full waveform configuration |
| `SET,WAVE,SINE` | Set waveform |
| `SET,FREQ,1000` | Set frequency |
| `SET,VPP,2.0` | Set amplitude |
| `SET,OFFSET,1.0` | Set offset |
| `SET,PHASE,90` | Set phase |
| `SET,DUTY,50` | Set duty cycle |
| `START` | Start waveform generation |
| `STOP` | Stop waveform generation |
| `PAUSE` | Pause output |
| `RESUME` | Resume output |
| `RESET` | Restore default settings |
| `STATUS` | Request device status |
| `SWEEP,CONFIG,F1=100,F2=10000,T=5,MODE=LOG` | Configure sweep |
| `SWEEP,START` | Start sweep |
| `SWEEP,STOP` | Stop sweep |

Sweep mode can be `LIN` or `LOG`, with duration in seconds.

### ESP32 to PC Responses

| Response | Meaning |
|---|---|
| `OK` or `OK,<text>` | Command accepted |
| `ERROR,<code>` | Command rejected |
| `RUNNING` | Output active |
| `STOPPED` | Output stopped |
| `PAUSED` | Output paused |
| `READY` | Device ready |
| `STATUS,...` | Current configuration and operating state |
| `MEAS,...` | Optional device-reported measurement |

Supported error codes include:

- `INVALID_COMMAND`
- `INVALID_PARAM`
- `FREQ_RANGE`
- `VPP_RANGE`
- `OFFSET_RANGE`
- `PHASE_RANGE`
- `DUTY_RANGE`
- `BUSY`

A STATUS response may contain waveform, frequency, voltage, offset, phase, duty cycle, operating state, sample rate, sample count, firmware version, and sweep state.

The optional `MEAS` response can report frequency, raw DAC value, and sample rate. It should not be interpreted as an independently verified physical measurement unless the hardware provides that capability.

### Example Communication Session

```text
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

## 11. Communication Notes

- Opening the serial port may reset the ESP32 because of DTR/RTS behavior.
- The GUI waits approximately 1.5 seconds before its first STATUS request.
- Live update resends CONFIG while running with a 250 ms debounce.
- Live updates are skipped when configured values exceed hardware limits.
- Pulse waveform defaults to 10% duty cycle.
- Square waveform uses 50% duty cycle.
- Unrecognized serial messages are displayed in the communication log.

## 12. Version History

| Version | Component | Description |
|---|---|---|
| `firmware-v1.0.0` | ESP32 | Initial firmware import and documentation |
| `gui-v1.0.0` | Python | Original GUI application |
| `gui-v2.0.0` | Python | Enlarged preview and redesigned workspace |

The original firmware was imported without source modifications.

The GUI V2 update changes the desktop interface without requiring firmware, wiring, dependency, or serial-protocol changes.

## 13. Version Control and Collaboration

The project uses Git and GitHub for collaborative development.

### Branches

| Branch | Purpose |
|---|---|
| `main` | Integrated firmware and GUI |
| `esp32-firmware` | Firmware development |
| `python-gui` | Python GUI development |
| `feat/gui-preview-redesign` | GUI V2 feature development |

Feature changes are reviewed and integrated using pull requests.

Firmware and GUI development histories are preserved independently.

## 14. Contributors

| Name | GitHub | Recorded contribution |
|---|---|---|
| Naveen Ram | NaveenRam30 | Repository setup, firmware import and review |
| Anagha Arunkumar | anaghaarunkumar | GUI import and review, release documentation |

See `CONTRIBUTORS.md` for additional information.

## 15. Testing and Verification

Software checks previously documented include:

- Python calculations
- Serial protocol parsing
- Waveform preview calculations
- Headless GUI smoke test using simulated ESP32 responses

These checks do not establish complete physical hardware validation.

The following require verification on the actual hardware:

- ESP32 firmware compilation and upload
- DAC waveform output
- Oscilloscope/DSO waveform observations
- GUI-to-ESP32 serial communication
- Frequency and amplitude accuracy
- End-to-end operation

The actual board model, Arduino core version, and test observations should be recorded in the hardware checklist or subsequent verification documentation.

## 16. Future Improvements

Potential improvements include:

- Automated firmware build checks
- Hardware waveform validation
- GUI-to-firmware integration tests
- Additional output-stage calibration
- Expanded test documentation
