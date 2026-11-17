
# ESP32 Function Generator — Changelog

This changelog records the development and integration of the ESP32 firmware and Python GUI.

## GUI v2.0.0 — Visibility Update

- Imported the redesigned Python GUI.
- Enlarged waveform preview with readable controls and resizable workspace.
- Added focus preview and F11/Esc fullscreen support.
- Added preview cycle and scale selection.
- Introduced tabbed settings and a separate details/log window.
- Preserved the existing serial protocol and firmware compatibility.

## GUI v1.0.0 — Original GUI

- Imported the original Python desktop application.
- Added waveform configuration and visualization.
- Included serial communication and command handling.
- Established the baseline for subsequent GUI improvements.

## Firmware v1.0.0 — Initial Firmware

- Imported the existing ESP32 waveform generator sketch without source modifications.
- Documented the internal DAC output on GPIO25.
- Documented the 115200-baud ASCII serial protocol.
- Recorded firmware version 1.0.0.

## Repository Integration

- Integrated ESP32 firmware into the main branch through Pull Request #2.
- Integrated Python GUI into the main branch through Pull Request #3.
- Preserved separate firmware and GUI development branches.

## Verification

Python calculations, protocol parsing and preview logic have undergone software checks.

Physical waveform output and complete firmware–GUI integration require hardware verification.
