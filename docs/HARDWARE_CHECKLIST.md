# Manual verification checklist

Run for each tagged release and record actual observations in the pull request.
The boxes below are deliberately unchecked; packaging did not verify hardware.

- [ ] Install requirements and launch `python main.py`.
- [ ] Connect to the correct ESP32 serial port at the configured baud rate.
- [ ] Verify Start, Stop, Pause/Resume and Reset.
- [ ] Check each waveform on the DSO at representative valid settings.
- [ ] Check frequency, Vpp, offset, duty cycle and input validation.
- [ ] Check sweep operation and status/log updates.
- [ ] Record firmware version and board/core configuration actually used.
- [ ] For V2, check resize, Focus preview, F11/Esc, cycle selection and scale modes.

The preview is a calculated waveform, not captured DSO data. Phase validation
requires an appropriate stable time reference; a single auto-triggered trace may
look unchanged. No phase-related firmware fix is included in these snapshots.
