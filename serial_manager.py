"""serial_manager.py - threaded serial link to the ESP32.

A single worker thread does all port I/O so the GUI never blocks:

* commands are queued with send() and transmitted one at a time;
* after each command the thread waits (up to ACK_TIMEOUT_S) for an
  acknowledgement (OK / ERROR / RUNNING / STOPPED / STATUS ...);
* everything that happens is reported to the GUI through `events`, a
  thread-safe queue that the GUI polls with Tk's after():

    ("tx", command)            command was written to the port
    ("rx_line", raw_text)      any line received (for the log)
    ("ack", command, Response) reply that answers `command`
    ("data", Response)         STATUS / MEAS / unsolicited replies
    ("timeout", command)       no acknowledgement in time
    ("error", text)            local error (e.g. not connected)
    ("disconnected", text)     the port failed (cable pulled, ...)
"""
import queue
import threading
import time

import serial
from serial.tools import list_ports

import config
import protocol


class SerialError(Exception):
    """Raised for problems opening the serial port."""


def list_serial_ports():
    """Return [(device, description), ...] for all detected serial ports."""
    try:
        ports = list_ports.comports()
    except Exception:
        return []
    return [(p.device, p.description or "serial port")
            for p in sorted(ports, key=lambda p: p.device)]


class SerialManager:
    def __init__(self):
        self.events = queue.Queue()
        self._tx = queue.Queue()
        self._ser = None
        self._thread = None
        self._stop = threading.Event()
        self._pending = None            # (command, deadline) awaiting a reply
        self.port = None
        self.baud = None

    # ------------------------------------------------------------ state
    @property
    def connected(self) -> bool:
        return (self._ser is not None and self._ser.is_open
                and self._thread is not None and self._thread.is_alive())

    @property
    def busy(self) -> bool:
        """True while a command is queued or waiting for its reply."""
        return self._pending is not None or not self._tx.empty()

    # ------------------------------------------------------- connection
    def connect(self, port: str, baud: int):
        if self.connected:
            raise SerialError("Already connected.")
        try:
            ser = serial.Serial(port=port, baudrate=baud, timeout=0.05,
                                write_timeout=1.0)
        except serial.SerialException as exc:
            raise SerialError(f"Cannot open {port}: {exc}") from exc
        except (ValueError, OSError) as exc:
            raise SerialError(f"Invalid serial settings for {port}: {exc}") from exc

        self._drain(self._tx)
        self._drain(self.events)
        self._stop.clear()
        self._pending = None
        self._ser, self.port, self.baud = ser, port, baud
        self._thread = threading.Thread(target=self._run, name="serial-io",
                                        daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._thread = None
        self._pending = None
        self.port = self.baud = None
        self._drain(self._tx)
        self._drain(self.events)

    # ---------------------------------------------------------- sending
    def send(self, command: str) -> bool:
        """Queue a command line. Returns False if not connected."""
        if not self.connected:
            self.events.put(("error", "Not connected to an ESP32."))
            return False
        self._tx.put(command.strip())
        return True

    # ------------------------------------------------------ worker thread
    def _run(self):
        ser = self._ser
        buf = bytearray()
        try:
            while not self._stop.is_set():
                # 1) transmit next command if we are not waiting for a reply
                if self._pending is None:
                    try:
                        cmd = self._tx.get_nowait()
                    except queue.Empty:
                        cmd = None
                    if cmd is not None:
                        ser.write((cmd + "\n").encode("ascii", "replace"))
                        self._pending = (cmd, time.monotonic() + config.ACK_TIMEOUT_S)
                        self.events.put(("tx", cmd))

                # 2) receive (blocks at most `timeout` = 50 ms)
                waiting = ser.in_waiting
                data = ser.read(waiting if waiting else 1)
                if data:
                    buf.extend(data)
                    while True:
                        idx = buf.find(b"\n")
                        if idx < 0:
                            break
                        raw = bytes(buf[:idx]).decode("utf-8", "replace").strip()
                        del buf[:idx + 1]
                        if raw:
                            self._handle_line(raw)
                    if len(buf) > 4096:          # garbage without newline
                        buf.clear()

                # 3) acknowledgement timeout
                pending = self._pending
                if pending is not None and time.monotonic() > pending[1]:
                    self._pending = None
                    self.events.put(("timeout", pending[0]))
        except (serial.SerialException, OSError) as exc:
            if not self._stop.is_set():
                self.events.put(("disconnected", str(exc) or "serial port error"))

    def _handle_line(self, raw: str):
        resp = protocol.parse_line(raw)
        self.events.put(("rx_line", raw))
        if resp.kind in ("STATUS", "MEAS"):
            self.events.put(("data", resp))
        pending = self._pending
        if pending is not None and resp.kind in protocol.ack_kinds(pending[0]):
            self._pending = None
            self.events.put(("ack", pending[0], resp))
        elif resp.kind not in ("STATUS", "MEAS"):
            self.events.put(("data", resp))

    @staticmethod
    def _drain(q: queue.Queue):
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass
