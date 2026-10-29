# ESP32 Function Generator — Firmware

Branch: `esp32-firmware`. Tag: `firmware-v1.0.0`.

Open `esp32_function_generator/esp32_function_generator.ino` in Arduino IDE.
The supplied sketch targets a classic ESP32 with an internal DAC (GPIO25 / DAC1).
Its source supports Arduino-ESP32 core 2.x/3.x via conditional compilation;
verify the actual board/core combination before flashing.

This is the unchanged sketch from both supplied completed-project archives.
Internal FW_VERSION is 1.0.0. Serial control is 115200 baud, newline-terminated
ASCII. Use the `python-gui` branch for the matching PC controller.

## Version history

- firmware-v1.0.0: import and review the existing ESP32 function generator sketch.
- No second distinct firmware version was present in the supplied archives.

## Verification

Record actual board, Arduino core, upload result and DSO observations here or in
a component pull request. Firmware compilation and hardware operation have not
been verified during repository packaging.

Future work: create `feat/firmware-description` or `fix/firmware-description`
from this branch; open pull requests with base `esp32-firmware`.
