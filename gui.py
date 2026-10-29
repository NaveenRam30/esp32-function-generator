"""gui.py - Tkinter front-end of the ESP32 function generator.

The GUI never talks to the serial port directly: it queues commands in
SerialManager and polls its event queue every 40 ms, so it cannot freeze.
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import calculations
import config
import protocol
import waveform
from config import COLORS as C
from config import GeneratorSettings
from serial_manager import SerialError, SerialManager, list_serial_ports

FONT_UI = ("Helvetica", 10)
FONT_BOLD = ("Helvetica", 10, "bold")
FONT_MONO = ("Courier", 11, "bold")
FONT_BIG = ("Helvetica", 22, "bold")
FONT_CHIP = ("Helvetica", 16, "bold")


# ======================================================================
# Styling
# ======================================================================
def apply_style(root: tk.Tk):
    root.configure(bg=C["bg"])
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=C["panel"], foreground=C["fg"],
                 fieldbackground=C["field"], bordercolor=C["border"],
                 lightcolor=C["panel"], darkcolor=C["panel"],
                 troughcolor=C["field"], font=FONT_UI, focuscolor=C["panel"])
    st.configure("TLabelframe", background=C["panel"], bordercolor=C["border"])
    st.configure("TLabelframe.Label", background=C["panel"],
                 foreground=C["accent"], font=FONT_BOLD)
    st.configure("Panel.TFrame", background=C["panel"])
    st.configure("TButton", background=C["panel2"], foreground=C["fg"],
                 padding=(8, 4), borderwidth=1)
    st.map("TButton",
           background=[("active", C["hover"]), ("disabled", C["panel"])],
           foreground=[("disabled", C["dim"])])
    st.configure("TEntry", fieldbackground=C["field"], foreground=C["fg"],
                 insertcolor=C["fg"])
    st.configure("Bad.TEntry", fieldbackground=C["bad_bg"], foreground=C["err"],
                 insertcolor=C["fg"])
    st.map("TEntry", fieldbackground=[("disabled", C["panel"])],
           foreground=[("disabled", C["dim"])])
    st.map("TCombobox",
           fieldbackground=[("readonly", C["field"])],
           foreground=[("readonly", C["fg"])],
           background=[("readonly", C["panel2"])],
           selectbackground=[("readonly", C["field"])],
           selectforeground=[("readonly", C["fg"])])
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["bg"])
    st.configure("Horizontal.TScale", background=C["panel"], troughcolor=C["field"])
    st.configure("TRadiobutton", background=C["panel"], foreground=C["fg"])
    st.configure("TCheckbutton", background=C["panel"], foreground=C["fg"])
    st.configure("Root.TCheckbutton", background=C["bg"], foreground=C["fg"])
    st.map("TRadiobutton", background=[("active", C["panel"])])
    st.map("TCheckbutton", background=[("active", C["panel"])])
    st.map("Root.TCheckbutton", background=[("active", C["bg"])])


def kv_grid(parent, items, ncols=2, start_row=0):
    """Create 'label  value' pairs in a grid; returns {key: value_label}."""
    labels = {}
    for i, (key, text) in enumerate(items):
        r = start_row + i // ncols
        c = (i % ncols) * 2
        ttk.Label(parent, text=text, foreground=C["dim"]).grid(
            row=r, column=c, sticky="w", padx=(6, 4), pady=1)
        lbl = ttk.Label(parent, text="\u2014", font=FONT_MONO)
        lbl.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=1)
        labels[key] = lbl
    return labels


# ======================================================================
# Reusable input widgets
# ======================================================================
class ParamControl:
    """Label + numeric entry + unit + slider, kept in sync and validated.

    * typing an invalid / out-of-range number turns the entry red, keeps the
      last valid value and stores a message in `self.error` (nothing is
      silently clipped);
    * `on_change(control, valid)` is called after every edit.
    """

    def __init__(self, parent, row, label, unit, vmin, vmax, default,
                 decimals, on_change, slider=True):
        self.label, self.unit = label, unit
        self.vmin, self.vmax, self.decimals = vmin, vmax, decimals
        self.on_change = on_change
        self.value = default
        self.error = ""
        self._lock = False
        self.var = tk.StringVar(value=self._fmt(default))
        self.svar = tk.DoubleVar(value=default)

        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           padx=(6, 8), pady=4)
        self.entry = ttk.Entry(parent, textvariable=self.var, width=9,
                               justify="right")
        self.entry.grid(row=row, column=1, sticky="w", pady=4)
        ttk.Label(parent, text=unit, foreground=C["dim"]).grid(
            row=row, column=2, sticky="w", padx=(4, 8))
        self.scale = None
        if slider:
            self.scale = ttk.Scale(parent, from_=vmin, to=vmax, variable=self.svar,
                                   orient="horizontal", command=self._on_scale)
            self.scale.grid(row=row, column=3, sticky="ew", padx=(0, 8))
        self.var.trace_add("write", lambda *_: self._on_entry())

    def _fmt(self, v):
        return f"{v:.{self.decimals}f}"

    def _set_error(self, msg):
        self.error = msg
        self.entry.configure(style="Bad.TEntry")
        self.on_change(self, False)

    def _on_entry(self, notify=True):
        if self._lock:
            return
        text = self.var.get().strip().replace(",", ".")
        try:
            v = float(text)
            if not math.isfinite(v):
                raise ValueError
        except ValueError:
            self._set_error(f"{self.label}: '{text}' is not a valid number.")
            return
        if v < self.vmin or v > self.vmax:
            self._set_error(f"{self.label}: {v:g} {self.unit} is outside the "
                            f"allowed range {self.vmin:g} to {self.vmax:g} {self.unit}.")
            return
        self.error = ""
        self.entry.configure(style="TEntry")
        self.value = v
        if self.scale is not None:
            self._lock = True
            self.svar.set(v)
            self._lock = False
        if notify:
            self.on_change(self, True)

    def _on_scale(self, raw):
        if self._lock:
            return
        v = round(float(raw), self.decimals)
        self.value = v
        self.error = ""
        self.entry.configure(style="TEntry")
        self._lock = True
        self.var.set(self._fmt(v))
        self._lock = False
        self.on_change(self, True)

    def set_value(self, v):
        """Programmatic change (presets, reset). Does not call on_change."""
        self._lock = True
        self.value = v
        self.error = ""
        self.entry.configure(style="TEntry")
        self.var.set(self._fmt(v))
        self.svar.set(v)
        self._lock = False

    def set_range(self, vmin, vmax):
        self.vmin, self.vmax = vmin, vmax
        if self.scale is not None:
            self.scale.configure(from_=vmin, to=vmax)
        self._on_entry(notify=False)     # re-validate the current text

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        if self.scale is not None:
            self.scale.configure(state=state)


class FreqControl:
    """Frequency entry with Hz/kHz selector and a logarithmic slider."""

    def __init__(self, parent, row, on_change):
        self.on_change = on_change
        self.value = 1000.0
        self.error = ""
        self.label = "Frequency"
        self._lock = False
        self.unit_var = tk.StringVar(value="Hz")
        self.var = tk.StringVar(value="1000")
        self.svar = tk.DoubleVar(value=self._to_pos(self.value))

        ttk.Label(parent, text="Frequency").grid(row=row, column=0, sticky="w",
                                                 padx=(6, 8), pady=4)
        self.entry = ttk.Entry(parent, textvariable=self.var, width=9,
                               justify="right")
        self.entry.grid(row=row, column=1, sticky="w", pady=4)
        self.unit = ttk.Combobox(parent, textvariable=self.unit_var, width=5,
                                 values=["Hz", "kHz"], state="readonly")
        self.unit.grid(row=row, column=2, sticky="w", padx=(4, 8))
        self.unit.bind("<<ComboboxSelected>>", lambda e: self._set_text())
        self.scale = ttk.Scale(parent, from_=0.0, to=1.0, variable=self.svar,
                               orient="horizontal", command=self._on_scale)
        self.scale.grid(row=row, column=3, sticky="ew", padx=(0, 8))
        self.var.trace_add("write", lambda *_: self._on_entry())

    @staticmethod
    def _to_pos(hz):
        lo, hi = config.FREQ_MIN_HZ, config.FREQ_MAX_HZ
        return min(max(math.log(hz / lo) / math.log(hi / lo), 0.0), 1.0)

    @staticmethod
    def _from_pos(x):
        lo, hi = config.FREQ_MIN_HZ, config.FREQ_MAX_HZ
        return lo * (hi / lo) ** x

    def _mult(self):
        return 1000.0 if self.unit_var.get() == "kHz" else 1.0

    def _set_text(self):
        self._lock = True
        self.var.set(f"{self.value / self._mult():.6g}")
        self._lock = False

    def _on_entry(self):
        if self._lock:
            return
        text = self.var.get().strip().replace(",", ".")
        try:
            hz = float(text) * self._mult()
            if not math.isfinite(hz):
                raise ValueError
        except ValueError:
            self.error = f"Frequency: '{text}' is not a valid number."
            self.entry.configure(style="Bad.TEntry")
            self.on_change(self, False)
            return
        if hz < config.FREQ_MIN_HZ or hz > config.FREQ_MAX_HZ:
            self.error = (f"Frequency: {calculations.format_frequency(hz)} is outside "
                          f"the allowed range "
                          f"{calculations.format_frequency(config.FREQ_MIN_HZ)} to "
                          f"{calculations.format_frequency(config.FREQ_MAX_HZ)}.")
            self.entry.configure(style="Bad.TEntry")
            self.on_change(self, False)
            return
        self.error = ""
        self.entry.configure(style="TEntry")
        self.value = hz
        self._lock = True
        self.svar.set(self._to_pos(hz))
        self._lock = False
        self.on_change(self, True)

    def _on_scale(self, raw):
        if self._lock:
            return
        hz = float(f"{self._from_pos(float(raw)):.3g}")       # 3 significant digits
        hz = min(max(hz, config.FREQ_MIN_HZ), config.FREQ_MAX_HZ)
        self.value = hz
        self.error = ""
        self.entry.configure(style="TEntry")
        self._set_text()
        self.on_change(self, True)

    def set_value(self, hz):
        self._lock = True
        self.value = hz
        self.error = ""
        self.entry.configure(style="TEntry")
        self.svar.set(self._to_pos(hz))
        self._lock = False
        self._set_text()


# ======================================================================
# Small formatting helpers for values reported by the ESP32
# ======================================================================
def _fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt_freq_field(x):
    v = _fnum(x)
    return "\u2014" if v is None else calculations.format_frequency(v)


def _fmt_rate(x):
    v = _fnum(x)
    if v is None:
        return "\u2014"
    return f"{v / 1000:.1f} kS/s" if v >= 1000 else f"{v:g} S/s"


def _fmt_dac(x):
    v = _fnum(x)
    if v is None:
        return "\u2014"
    full = (1 << config.DAC_BITS) - 1
    return f"{v:g} / {full}  (\u2248{v / full * config.DAC_DIRECT_MAX_V:.2f} V)"


# ======================================================================
# Main application
# ======================================================================
class FunctionGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(config.APP_TITLE)
        root.geometry("1400x990")
        root.minsize(1150, 820)
        apply_style(root)
        root.report_callback_exception = self._on_tk_exception

        self.mgr = SerialManager()
        self.connected = False
        self.run_state = "Unknown"          # Unknown / Stopped / Running / Paused
        self.esp_alive = None               # None = unknown, True/False
        self.missed_status = 0
        self.port_map = {}
        self.reported = {}                  # fields of the last STATUS reply
        self.measured = {}                  # fields of the last MEAS reply
        self.sweeping = False
        self._refresh_job = None
        self._live_job = None
        self._poll_after = 0.0
        self._prev_wave = "Sine"

        self._build_ui()
        self._set_connected(False)
        self._refresh_ports()
        self._update_duty_state()
        self._refresh()
        self._set_state("Unknown")

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(40, self._poll_events)
        root.after(config.PORT_REFRESH_MS, self._port_timer)
        root.after(config.STATUS_POLL_MS, self._status_timer)

    # ==================================================================
    # UI construction
    # ==================================================================
    def _panel(self, parent, title):
        return ttk.LabelFrame(parent, text=f" {title} ", padding=6)

    def _build_ui(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(2, weight=1)          # preview grows with the window
        self._build_header()
        self._build_top()
        self._build_preview()
        self._build_summary()
        self._build_buttons()
        self._build_log()

    # ---------------------------------------------------------- header
    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C["header"])
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text=config.APP_TITLE, bg=C["header"], fg=C["accent"],
                 font=("Helvetica", 18, "bold")).pack(side="left", padx=16, pady=8)
        self.hdr_state = tk.Label(hdr, text="\u25cf DISCONNECTED", bg=C["header"],
                                  fg=C["err"], font=("Helvetica", 13, "bold"))
        self.hdr_state.pack(side="right", padx=16)

    # ------------------------------------------------- three-column area
    def _build_top(self):
        top = tk.Frame(self.root, bg=C["bg"])
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 4))
        top.columnconfigure(0, weight=2, uniform="col")
        top.columnconfigure(1, weight=3, uniform="col")
        top.columnconfigure(2, weight=3, uniform="col")
        left = tk.Frame(top, bg=C["bg"])
        mid = tk.Frame(top, bg=C["bg"])
        right = tk.Frame(top, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        mid.grid(row=0, column=1, sticky="nsew", padx=6)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        for col in (left, mid, right):
            col.columnconfigure(0, weight=1)
        self._build_connection(left)
        self._build_presets(left)
        self._build_sweep(left)
        self._build_config(mid)
        self._build_hardware(mid)
        self._build_esp_status(right)
        self._build_output_info(right)
        self._build_monitor(right)

    def _build_connection(self, parent):
        p = self._panel(parent, "CONNECTION")
        p.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        p.columnconfigure(1, weight=1)
        ttk.Label(p, text="COM Port").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(p, textvariable=self.port_var, width=26,
                                       state="readonly")
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(p, text="Refresh", width=8, command=self._refresh_ports).grid(
            row=0, column=2, padx=(0, 4))
        ttk.Label(p, text="Baud Rate").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.baud_var = tk.StringVar(value=str(config.DEFAULT_BAUD))
        ttk.Combobox(p, textvariable=self.baud_var, width=12, state="readonly",
                     values=[str(b) for b in config.BAUD_RATES]).grid(
            row=1, column=1, sticky="w", padx=4)
        btns = ttk.Frame(p, style="Panel.TFrame")
        btns.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        self.btn_connect = ttk.Button(btns, text="Connect", command=self.on_connect)
        self.btn_connect.pack(side="left", padx=4)
        self.btn_disconnect = ttk.Button(btns, text="Disconnect",
                                         command=self.on_disconnect)
        self.btn_disconnect.pack(side="left", padx=4)
        self.conn_status = ttk.Label(p, text="\u25cf Disconnected",
                                     foreground=C["err"], font=FONT_BOLD)
        self.conn_status.grid(row=3, column=0, columnspan=3, sticky="w", padx=6)
        self.conn_port = ttk.Label(p, text="Port: \u2014", foreground=C["dim"])
        self.conn_port.grid(row=4, column=0, columnspan=3, sticky="w", padx=6)

    def _build_presets(self, parent):
        p = self._panel(parent, "PRESETS")
        p.grid(row=1, column=0, sticky="ew", pady=6)
        p.columnconfigure((0, 1), weight=1)
        for i, name in enumerate(config.PRESETS):
            ttk.Button(p, text=name, command=lambda n=name: self._apply_preset(n)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=3, pady=2)
        ttk.Button(p, text="Custom", command=self._set_custom).grid(
            row=2, column=1, sticky="ew", padx=3, pady=2)
        self.mode_var = tk.StringVar(value="Mode: Custom")
        ttk.Label(p, textvariable=self.mode_var, foreground=C["dim"]).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))

    def _build_sweep(self, parent):
        p = self._panel(parent, "FREQUENCY SWEEP")
        p.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        p.columnconfigure(3, weight=1)
        noop = lambda c, v: None
        self.sw_start = ParamControl(p, 0, "Start", "Hz", config.FREQ_MIN_HZ,
                                     config.FREQ_MAX_HZ, 100.0, 1, noop, slider=False)
        self.sw_stop = ParamControl(p, 1, "Stop", "Hz", config.FREQ_MIN_HZ,
                                    config.FREQ_MAX_HZ, 10000.0, 1, noop, slider=False)
        self.sw_time = ParamControl(p, 2, "Duration", "s", config.SWEEP_TIME_MIN_S,
                                    config.SWEEP_TIME_MAX_S, 5.0, 1, noop, slider=False)
        self.sweep_mode = tk.StringVar(value="LIN")
        mode = ttk.Frame(p, style="Panel.TFrame")
        mode.grid(row=3, column=0, columnspan=4, sticky="w", padx=4)
        ttk.Radiobutton(mode, text="Linear", value="LIN",
                        variable=self.sweep_mode).pack(side="left", padx=4)
        ttk.Radiobutton(mode, text="Logarithmic", value="LOG",
                        variable=self.sweep_mode).pack(side="left", padx=4)
        b = ttk.Frame(p, style="Panel.TFrame")
        b.grid(row=4, column=0, columnspan=4, sticky="w", pady=4)
        self.btn_sw_start = ttk.Button(b, text="Start sweep", command=self.on_sweep_start)
        self.btn_sw_start.pack(side="left", padx=4)
        self.btn_sw_stop = ttk.Button(b, text="Stop sweep", command=self.on_sweep_stop)
        self.btn_sw_stop.pack(side="left", padx=4)
        self.sweep_lbl = ttk.Label(p, text="Sweep: idle", foreground=C["dim"])
        self.sweep_lbl.grid(row=5, column=0, columnspan=4, sticky="w", padx=6)

    # ------------------------------------------------- waveform config
    def _build_config(self, parent):
        p = self._panel(parent, "WAVEFORM CONFIGURATION")
        p.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        p.columnconfigure(3, weight=1)

        ro = ttk.Frame(p, style="Panel.TFrame")           # big read-outs
        ro.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 6))
        self.big_freq = ttk.Label(ro, text="", font=FONT_BIG, foreground=C["accent"])
        self.big_freq.pack(side="left", padx=(6, 24))
        self.big_vpp = ttk.Label(ro, text="", font=FONT_BIG, foreground=C["trace"])
        self.big_vpp.pack(side="left")

        ttk.Label(p, text="Waveform").grid(row=1, column=0, sticky="w", padx=(6, 8), pady=4)
        self.wave_var = tk.StringVar(value="Sine")
        self.wave_combo = ttk.Combobox(p, textvariable=self.wave_var, width=12,
                                       values=config.WAVEFORMS, state="readonly")
        self.wave_combo.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        self.wave_combo.bind("<<ComboboxSelected>>", lambda e: self._on_wave_change())

        lo, hi = config.OUTPUT_MODES[config.DEFAULT_OUTPUT_MODE]
        cb = self._on_param_change
        self.freq = FreqControl(p, 2, cb)
        self.vpp = ParamControl(p, 3, "Amplitude (Vpp)", "V", config.VPP_MIN,
                                config.VPP_MAX, 2.0, 2, cb)
        self.offset = ParamControl(p, 4, "DC Offset", "V", lo, hi, 1.0, 2, cb)
        self.phase = ParamControl(p, 5, "Phase", "\u00b0", config.PHASE_MIN,
                                  config.PHASE_MAX, 0.0, 0, cb)
        ttk.Button(p, text="Reset phase", command=self._reset_phase).grid(
            row=5, column=4, padx=(0, 6))
        self.duty = ParamControl(p, 6, "Duty Cycle", "%", config.DUTY_MIN,
                                 config.DUTY_MAX, 50.0, 0, cb)

        ttk.Label(p, text=("Vpp = peak-to-peak (the controlled value).  Peak = Vpp/2.  "
                           "RMS depends on the waveform (see Output Information)."),
                  foreground=C["dim"], wraplength=520).grid(
            row=7, column=0, columnspan=5, sticky="w", padx=6, pady=(4, 0))
        self.expected_lbl = ttk.Label(p, text="", font=FONT_BOLD)
        self.expected_lbl.grid(row=8, column=0, columnspan=5, sticky="w", padx=6, pady=2)
        self.error_lbl = ttk.Label(p, text="", foreground=C["err"], wraplength=520)
        self.error_lbl.grid(row=9, column=0, columnspan=5, sticky="w", padx=6)

    def _build_hardware(self, parent):
        p = self._panel(parent, "HARDWARE OUTPUT LIMITS")
        p.grid(row=1, column=0, sticky="ew", pady=6)
        p.columnconfigure(1, weight=1)
        ttk.Label(p, text="Output configuration").grid(row=0, column=0, sticky="w", padx=6)
        self.out_mode_var = tk.StringVar(value=config.DEFAULT_OUTPUT_MODE)
        cb = ttk.Combobox(p, textvariable=self.out_mode_var, state="readonly",
                          values=list(config.OUTPUT_MODES), width=34)
        cb.grid(row=0, column=1, sticky="w", padx=4, pady=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_output_mode())
        ttk.Label(p, text=config.HW_LIMIT_MESSAGE, foreground=C["dim"],
                  wraplength=520).grid(row=1, column=0, columnspan=2, sticky="w",
                                       padx=6, pady=2)
        self.warn_lbl = ttk.Label(p, text="", wraplength=520, font=FONT_BOLD)
        self.warn_lbl.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=2)

    # ---------------------------------------------------- right column
    def _build_esp_status(self, parent):
        p = self._panel(parent, "ESP32 STATUS")
        p.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.state_lbl = ttk.Label(p, text="", font=FONT_BIG)
        self.state_lbl.grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 4))
        self.st = kv_grid(p, [
            ("conn", "Link"), ("port", "Port"),
            ("wave", "Waveform"), ("freq", "Frequency"),
            ("vpp", "Amplitude"), ("phase", "Phase"),
            ("state", "Output"), ("fs", "Sample rate"),
            ("samples", "Samples"), ("fw", "Firmware"),
        ], start_row=1)

    def _build_output_info(self, parent):
        p = self._panel(parent, "OUTPUT INFORMATION (configured)")
        p.grid(row=1, column=0, sticky="ew", pady=6)
        self.info = kv_grid(p, [
            ("wave", "Waveform"), ("freq", "Frequency"),
            ("vpp", "Vpp"), ("peak", "Peak"),
            ("rms_ac", "RMS (AC)"), ("rms_tot", "RMS (total)"),
            ("offset", "DC offset"), ("phase", "Phase"),
            ("duty", "Duty"), ("vmin", "Min voltage"),
            ("vmax", "Max voltage"),
        ])

    def _build_monitor(self, parent):
        p = self._panel(parent, "MONITORING  (configured vs. measured)")
        p.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        heads = ["", "Configured (PC)", "Reported (ESP32)", "Measured"]
        for c, h in enumerate(heads):
            ttk.Label(p, text=h, foreground=C["dim"], font=FONT_BOLD).grid(
                row=0, column=c, sticky="w", padx=6)
        self.mon = {}
        for r, (key, name) in enumerate([("freq", "Frequency"), ("state", "Output state"),
                                         ("dac", "DAC level"), ("fs", "Sample rate")], 1):
            ttk.Label(p, text=name).grid(row=r, column=0, sticky="w", padx=6, pady=1)
            cells = []
            for c in (1, 2, 3):
                lbl = ttk.Label(p, text="\u2014", font=FONT_MONO)
                lbl.grid(row=r, column=c, sticky="w", padx=6, pady=1)
                cells.append(lbl)
            self.mon[key] = cells

    # ---------------------------------------------------------- preview
    def _build_preview(self):
        frame = ttk.LabelFrame(self.root, text=" WAVEFORM PREVIEW (software estimate) ",
                               padding=4)
        frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.fig = Figure(figsize=(9, 3.2), dpi=100, facecolor=C["panel"])
        self.ax = self.fig.add_subplot(111)
        ax = self.ax
        ax.set_facecolor(C["plot_bg"])
        ax.grid(True, color=C["grid"], linewidth=0.8)
        for spine in ax.spines.values():
            spine.set_color(C["border"])
        ax.tick_params(colors=C["dim"])
        ax.xaxis.label.set_color(C["fg"])
        ax.yaxis.label.set_color(C["fg"])
        ax.set_ylabel("Voltage (V)")
        self.line, = ax.plot([], [], color=C["trace"], linewidth=1.8)
        self.hw_lines = [
            ax.axhline(0, color=C["warn"], linestyle="--", linewidth=1, alpha=0.7,
                       label="Hardware limits"),
            ax.axhline(3.3, color=C["warn"], linestyle="--", linewidth=1, alpha=0.7),
        ]
        ax.legend(loc="upper right", facecolor=C["panel"], edgecolor=C["border"],
                  labelcolor=C["dim"], fontsize=8)
        self.fig.subplots_adjust(left=0.07, right=0.985, top=0.87, bottom=0.18)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _build_summary(self):
        f = tk.Frame(self.root, bg=C["bg"])
        f.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        self.chips = {}
        for i, (key, title) in enumerate([("vpp", "Vpp"), ("rms", "RMS"),
                                          ("offset", "Offset"), ("phase", "Phase"),
                                          ("freq", "Frequency"), ("duty", "Duty")]):
            f.columnconfigure(i, weight=1, uniform="chip")
            chip = tk.Frame(f, bg=C["panel2"], highlightbackground=C["border"],
                            highlightthickness=1)
            chip.grid(row=0, column=i, sticky="ew", padx=3)
            tk.Label(chip, text=title, bg=C["panel2"], fg=C["dim"],
                     font=("Helvetica", 9)).pack(pady=(4, 0))
            lbl = tk.Label(chip, text="\u2014", bg=C["panel2"], fg=C["fg"], font=FONT_CHIP)
            lbl.pack(pady=(0, 4))
            self.chips[key] = lbl

    def _build_buttons(self):
        f = tk.Frame(self.root, bg=C["bg"])
        f.grid(row=4, column=0, sticky="ew", padx=10, pady=4)
        for i in range(4):
            f.columnconfigure(i, weight=1)
        self.ctrl_buttons = []
        specs = [("START", C["ok"], self.on_start), ("STOP", C["err"], self.on_stop),
                 ("PAUSE", C["warn"], self.on_pause), ("RESET", "#9aa7b5", self.on_reset)]
        for i, (text, color, cmd) in enumerate(specs):
            b = tk.Button(f, text=text, command=cmd, bg=color, fg="#0b0e11",
                          activebackground=color, disabledforeground="#5b6672",
                          font=("Helvetica", 14, "bold"), height=2, relief="flat",
                          bd=0, cursor="hand2")
            b.grid(row=0, column=i, sticky="ew", padx=6)
            self.ctrl_buttons.append((b, color))
        self.btn_start, self.btn_stop, self.btn_pause, self.btn_reset = (
            b for b, _ in self.ctrl_buttons)
        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Live update while running (re-send CONFIG when a value changes)",
                        variable=self.live_var, style="Root.TCheckbutton").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 0))

    def _build_log(self):
        f = tk.Frame(self.root, bg=C["bg"])
        f.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 0))
        f.columnconfigure(0, weight=1)
        self.log = tk.Text(f, height=5, bg=C["field"], fg=C["fg"], bd=0,
                           highlightthickness=1, highlightbackground=C["border"],
                           font=("Courier", 9), state="disabled", wrap="none")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.grid(row=0, column=0, sticky="ew")
        sb.grid(row=0, column=1, sticky="ns")
        self.log.tag_configure("tx", foreground=C["accent"])
        self.log.tag_configure("rx", foreground=C["fg"])
        self.log.tag_configure("info", foreground=C["dim"])
        self.log.tag_configure("ok", foreground=C["ok"])
        self.log.tag_configure("warn", foreground=C["warn"])
        self.log.tag_configure("err", foreground=C["err"])
        self.msg_lbl = tk.Label(self.root, text="Ready.", anchor="w", bg=C["header"],
                                fg=C["dim"], font=FONT_UI)
        self.msg_lbl.grid(row=6, column=0, sticky="ew", pady=(4, 0), ipady=3)

    # ==================================================================
    # Logging / messages
    # ==================================================================
    def _log(self, text, tag="info"):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 500:
            self.log.delete("1.0", "2.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_message(self, text, level="info"):
        colors = {"info": C["fg"], "ok": C["ok"], "warn": C["warn"], "err": C["err"]}
        self.msg_lbl.configure(text=" " + text, fg=colors.get(level, C["fg"]))
        self._log(text, level)

    def _on_tk_exception(self, exc, val, tb):
        self._set_message(f"Internal error: {val!r}", "err")

    # ==================================================================
    # Settings helpers
    # ==================================================================
    def _settings(self) -> GeneratorSettings:
        return GeneratorSettings(
            wave=self.wave_var.get(), freq_hz=self.freq.value, vpp=self.vpp.value,
            offset=self.offset.value, phase_deg=self.phase.value,
            duty_pct=self.duty.value)

    def _hw_range(self):
        return config.OUTPUT_MODES[self.out_mode_var.get()]

    def _hw_warnings(self):
        lo, hi = self._hw_range()
        return calculations.hardware_warnings(self._settings(), lo, hi)

    def _active_controls(self):
        ctrls = [self.freq, self.vpp, self.offset, self.phase]
        if self.wave_var.get() in config.DUTY_WAVEFORMS:
            ctrls.append(self.duty)
        return ctrls

    def _errors(self):
        return [c.error for c in self._active_controls() if c.error]

    # ==================================================================
    # Control callbacks
    # ==================================================================
    def _on_param_change(self, ctrl, valid=True):
        if valid:
            self.mode_var.set("Mode: Custom")
            self._schedule_live()
        self._schedule_refresh()

    def _on_wave_change(self):
        wave = self.wave_var.get()
        # Switching to Pulse from a non-duty waveform (or from a 50 % square)
        # starts with a narrow 10 % pulse so it looks different from a square.
        if wave == "Pulse" and (self._prev_wave not in config.DUTY_WAVEFORMS
                                or (self._prev_wave == "Square" and self.duty.value == 50.0)):
            self.duty.set_value(10.0)
        self._prev_wave = wave
        self._update_duty_state()
        self.mode_var.set("Mode: Custom")
        self._schedule_refresh()
        self._schedule_live()

    def _update_duty_state(self):
        self.duty.set_enabled(self.wave_var.get() in config.DUTY_WAVEFORMS)

    def _reset_phase(self):
        self.phase.set_value(0.0)
        self._on_param_change(self.phase, True)

    def _on_output_mode(self):
        lo, hi = self._hw_range()
        self.offset.set_range(lo, hi)
        self._schedule_refresh()

    def _apply_preset(self, name):
        wave, freq = config.PRESETS[name]
        self.wave_var.set(wave)
        self._prev_wave = wave
        self.freq.set_value(freq)
        if wave in config.DUTY_WAVEFORMS:
            self.duty.set_value(50.0)
        self._update_duty_state()
        self.mode_var.set(f"Mode: Preset \u2013 {name}")
        self._schedule_refresh()
        self._schedule_live()

    def _set_custom(self):
        self.mode_var.set("Mode: Custom")

    def _reset_controls(self):
        d = GeneratorSettings()
        self.wave_var.set(d.wave)
        self._prev_wave = d.wave
        self.freq.set_value(d.freq_hz)
        self.vpp.set_value(d.vpp)
        self.offset.set_value(d.offset)
        self.phase.set_value(d.phase_deg)
        self.duty.set_value(d.duty_pct)
        self._update_duty_state()
        self.mode_var.set("Mode: Custom")
        self._schedule_refresh()

    # ==================================================================
    # Refresh of all read-outs and the plot
    # ==================================================================
    def _schedule_refresh(self):
        if self._refresh_job is None:
            self._refresh_job = self.root.after(20, self._refresh)

    def _refresh(self):
        self._refresh_job = None
        s = self._settings()
        hw_lo, hw_hi = self._hw_range()
        lo, hi = calculations.output_limits(s.vpp, s.offset)
        peak = calculations.peak_voltage(s.vpp)
        rms_ac = calculations.rms_ac(s.wave, s.vpp, s.duty_pct)
        rms_tot = calculations.rms_total(s.wave, s.vpp, s.offset, s.duty_pct)
        duty_on = s.wave in config.DUTY_WAVEFORMS
        freq_txt = calculations.format_frequency(s.freq_hz)
        duty_txt = f"{s.duty_pct:g} %" if duty_on else "n/a"
        warnings = calculations.hardware_warnings(s, hw_lo, hw_hi)

        # big read-outs
        self.big_freq.configure(text=freq_txt)
        self.big_vpp.configure(text=f"{s.vpp:.2f} Vpp")

        # output information
        vals = {
            "wave": s.wave, "freq": freq_txt, "vpp": f"{s.vpp:.3f} V",
            "peak": f"{peak:.3f} V", "rms_ac": f"{rms_ac:.3f} V",
            "rms_tot": f"{rms_tot:.3f} V", "offset": f"{s.offset:.3f} V",
            "phase": f"{s.phase_deg:g}\u00b0", "duty": duty_txt,
            "vmin": f"{lo:.3f} V", "vmax": f"{hi:.3f} V",
        }
        for k, v in vals.items():
            self.info[k].configure(text=v)

        # summary chips
        self.chips["vpp"].configure(text=f"{s.vpp:.2f} V")
        self.chips["rms"].configure(text=f"{rms_ac:.2f} V")
        self.chips["offset"].configure(text=f"{s.offset:.2f} V")
        self.chips["phase"].configure(text=f"{s.phase_deg:g}\u00b0")
        self.chips["freq"].configure(text=freq_txt)
        self.chips["duty"].configure(text=duty_txt)

        # expected output range + warnings + input errors
        self.expected_lbl.configure(
            text=f"Expected output:  min {lo:.2f} V   max {hi:.2f} V",
            foreground=C["warn"] if warnings else C["ok"])
        if warnings:
            self.warn_lbl.configure(
                text="\n".join("WARNING: " + w for w in warnings), foreground=C["warn"])
        else:
            self.warn_lbl.configure(
                text="OK: requested output is within the selected hardware range.",
                foreground=C["ok"])
        self.error_lbl.configure(text="\n".join(self._errors()))

        # plot
        t, v, unit, scale = waveform.preview(s)
        self.line.set_data(t * scale, v)
        self.line.set_color(C["warn"] if warnings else C["trace"])
        self.ax.set_xlim(0, t[-1] * scale)
        ymin, ymax = min(lo, hw_lo), max(hi, hw_hi)
        pad = max(0.25, 0.12 * (ymax - ymin))
        self.ax.set_ylim(ymin - pad, ymax + pad)
        self.hw_lines[0].set_ydata([hw_lo, hw_lo])
        self.hw_lines[1].set_ydata([hw_hi, hw_hi])
        self.ax.set_xlabel(f"Time ({unit})")
        title = (f"{s.wave}   |   {freq_txt}   |   {s.vpp:.2f} Vpp   |   "
                 f"offset {s.offset:.2f} V   |   phase {s.phase_deg:g}\u00b0")
        if duty_on:
            title += f"   |   duty {s.duty_pct:g} %"
        self.ax.set_title(title, color=C["fg"], fontsize=10)
        self.canvas.draw_idle()

        self._update_monitor()

    # ==================================================================
    # ESP32 status / monitoring panels
    # ==================================================================
    def _update_status_panel(self):
        rep = self.reported
        if not self.connected:
            conn, color = "Disconnected", C["err"]
        elif self.esp_alive:
            conn, color = "ESP32 replies", C["ok"]
        elif self.esp_alive is False:
            conn, color = "No reply", C["warn"]
        else:
            conn, color = "Waiting...", C["dim"]
        self.st["conn"].configure(text=conn, foreground=color)
        self.st["port"].configure(text=self.mgr.port or "\u2014")
        vpp = _fnum(rep.get("VPP"))
        phase = _fnum(rep.get("PHASE"))
        self.st["wave"].configure(text=rep.get("WAVE", "\u2014"))
        self.st["freq"].configure(text=_fmt_freq_field(rep.get("FREQ")))
        self.st["vpp"].configure(text="\u2014" if vpp is None else f"{vpp:.2f} Vpp")
        self.st["phase"].configure(text="\u2014" if phase is None else f"{phase:g}\u00b0")
        self.st["state"].configure(text=rep.get("STATE", "\u2014"))
        self.st["fs"].configure(text=_fmt_rate(rep.get("FS")))
        self.st["samples"].configure(text=rep.get("SAMPLES", "\u2014"))
        self.st["fw"].configure(text=rep.get("FW", "\u2014"))

    def _update_monitor(self):
        s = self._settings()
        rep, meas = self.reported, self.measured
        mf = _fnum(meas.get("FREQ"))
        meas_freq = _fmt_freq_field(meas.get("FREQ"))
        if mf is not None and s.freq_hz > 0:
            meas_freq += f" ({(mf - s.freq_hz) / s.freq_hz * 100:+.2f}%)"
        rows = {
            "freq": (calculations.format_frequency(s.freq_hz),
                     _fmt_freq_field(rep.get("FREQ")), meas_freq),
            "state": (self.run_state.upper(), rep.get("STATE", "\u2014"), "\u2014"),
            "dac": ("\u2014", "\u2014", _fmt_dac(meas.get("DAC", rep.get("DAC")))),
            "fs": ("\u2014", _fmt_rate(rep.get("FS")), _fmt_rate(meas.get("FS"))),
        }
        for key, values in rows.items():
            for lbl, text in zip(self.mon[key], values):
                lbl.configure(text=text)

    def _set_state(self, state):
        self.run_state = state
        colors = {"Running": C["ok"], "Stopped": C["err"], "Paused": C["warn"],
                  "Unknown": C["dim"]}
        text = state.upper() if self.connected else "OFFLINE"
        self.state_lbl.configure(text=text, foreground=colors.get(state, C["dim"]))
        self.btn_pause.configure(text="RESUME" if state == "Paused" else "PAUSE")
        if hasattr(self, "mon"):
            self._update_monitor()

    def _set_sweep(self, running):
        self.sweeping = running
        self.sweep_lbl.configure(text="Sweep: RUNNING" if running else "Sweep: idle",
                                 foreground=C["accent"] if running else C["dim"])

    # ==================================================================
    # Connection handling
    # ==================================================================
    def _preferred_port(self, names):
        hints = ("CP210", "CH340", "CH910", "FTDI", "Silicon", "UART", "USB")
        for n in names:
            if any(h.lower() in n.lower() for h in hints):
                return n
        return names[0]

    def _refresh_ports(self):
        new_map = {f"{dev} - {desc}": dev for dev, desc in list_serial_ports()}
        if list(new_map) == list(self.port_map):
            return
        current = self.port_var.get()
        self.port_map = new_map
        self.port_combo["values"] = list(new_map)
        if current in new_map:
            return
        self.port_var.set(self._preferred_port(list(new_map)) if new_map else "")
        if not new_map and not self.connected:
            self.conn_port.configure(text="No serial ports detected")

    def _port_timer(self):
        if not self.connected:
            self._refresh_ports()
        self.root.after(config.PORT_REFRESH_MS, self._port_timer)

    def _status_timer(self):
        if (self.connected and not self.mgr.busy
                and time.monotonic() >= self._poll_after):
            self.mgr.send(protocol.CMD_STATUS)
        self.root.after(config.STATUS_POLL_MS, self._status_timer)

    def on_connect(self):
        device = self.port_map.get(self.port_var.get())
        if not device:
            messagebox.showerror("Connection", "No valid serial port selected.\n"
                                 "Plug in the ESP32 and press Refresh.")
            return
        try:
            baud = int(self.baud_var.get())
        except ValueError:
            messagebox.showerror("Connection", "Invalid baud rate.")
            return
        try:
            self.mgr.connect(device, baud)
        except SerialError as exc:
            self._set_message(str(exc), "err")
            messagebox.showerror("Connection failed", str(exc))
            return
        self.reported, self.measured = {}, {}
        self.missed_status = 0
        self.esp_alive = None
        self._poll_after = time.monotonic() + config.CONNECT_SETTLE_S
        self._set_connected(True)
        self._set_message(f"Port {device} opened at {baud} baud.", "ok")

    def on_disconnect(self):
        self.mgr.disconnect()
        self._set_connected(False)
        self._set_message("Disconnected.", "info")

    def _on_link_lost(self, reason):
        self.mgr.disconnect()
        self._set_connected(False)
        self._set_message(f"ESP32 disconnected: {reason}", "err")
        messagebox.showerror("ESP32 disconnected",
                             f"The serial connection was lost.\n\n{reason}")

    def _set_connected(self, connected):
        self.connected = connected
        if connected:
            self.hdr_state.configure(text="\u25cf CONNECTED", fg=C["ok"])
            self.conn_status.configure(text="\u25cf Connected", foreground=C["ok"])
            self.conn_port.configure(text=f"Port: {self.mgr.port} @ {self.mgr.baud} baud")
            self.btn_connect.state(["disabled"])
            self.btn_disconnect.state(["!disabled"])
        else:
            self.hdr_state.configure(text="\u25cf DISCONNECTED", fg=C["err"])
            self.conn_status.configure(text="\u25cf Disconnected", foreground=C["err"])
            self.conn_port.configure(text="Port: \u2014")
            self.btn_connect.state(["!disabled"])
            self.btn_disconnect.state(["disabled"])
            self.esp_alive = None
            self._set_sweep(False)
        for b, color in self.ctrl_buttons:
            b.configure(state="normal" if connected else "disabled",
                        bg=color if connected else C["panel2"])
        for b in (self.btn_sw_start, self.btn_sw_stop):
            b.state(["!disabled"] if connected else ["disabled"])
        self._set_state("Unknown" if not connected else self.run_state)
        self._update_status_panel()

    def _on_close(self):
        self.mgr.disconnect()
        self.root.destroy()

    # ==================================================================
    # Buttons
    # ==================================================================
    def _send_config(self):
        return self.mgr.send(protocol.cmd_config(self._settings()))

    def _validate_before_sending(self):
        """Common checks. Returns True if the configuration may be sent."""
        errors = self._errors()
        if errors:
            messagebox.showerror("Invalid parameter",
                                 "Please correct these values first:\n\n" + "\n".join(errors))
            return False
        warnings = self._hw_warnings()
        if warnings:
            text = ("\n\n".join(warnings) +
                    "\n\nThe ESP32 cannot directly generate this. "
                    "Send the configuration anyway?")
            return messagebox.askyesno("Hardware limitation", text, icon="warning")
        return True

    def on_start(self):
        if not self._validate_before_sending():
            return
        self._send_config()
        self.mgr.send(protocol.CMD_START)
        self._set_message("Configuration and START sent, waiting for ESP32...", "info")

    def on_stop(self):
        self.mgr.send(protocol.CMD_STOP)

    def on_pause(self):
        if self.run_state == "Stopped":
            self._set_message("Nothing to pause: the output is stopped.", "warn")
            return
        self.mgr.send(protocol.CMD_RESUME if self.run_state == "Paused"
                      else protocol.CMD_PAUSE)

    def on_reset(self):
        self.mgr.send(protocol.CMD_RESET)
        self._reset_controls()

    def on_sweep_start(self):
        errs = [c.error for c in (self.sw_start, self.sw_stop, self.sw_time) if c.error]
        if errs:
            messagebox.showerror("Invalid sweep parameter", "\n".join(errs))
            return
        if self.sw_start.value == self.sw_stop.value:
            messagebox.showerror("Invalid sweep parameter",
                                 "Start and stop frequency must be different.")
            return
        if not self._validate_before_sending():
            return
        self._send_config()
        self.mgr.send(protocol.cmd_sweep_config(
            self.sw_start.value, self.sw_stop.value, self.sw_time.value,
            self.sweep_mode.get() == "LOG"))
        self.mgr.send(protocol.CMD_SWEEP_START)

    def on_sweep_stop(self):
        self.mgr.send(protocol.CMD_SWEEP_STOP)

    # -------------------------------------------------- live updating
    def _schedule_live(self):
        if not (self.live_var.get() and self.connected and self.run_state == "Running"):
            return
        if self._live_job is not None:
            self.root.after_cancel(self._live_job)
        self._live_job = self.root.after(config.LIVE_DEBOUNCE_MS, self._send_live)

    def _send_live(self):
        self._live_job = None
        if self._errors():
            return
        if self._hw_warnings():
            self._set_message("Live update skipped: value exceeds the hardware "
                              "range (see warnings).", "warn")
            return
        self._send_config()

    # ==================================================================
    # Events from the serial thread
    # ==================================================================
    def _poll_events(self):
        try:
            for _ in range(200):
                event = self.mgr.events.get_nowait()
                self._handle_event(event)
        except Exception:
            pass                                     # queue.Empty ends the loop
        self.root.after(40, self._poll_events)

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "tx":
            self._log(f"\u2192 {ev[1]}", "tx")
        elif kind == "rx_line":
            self._log(f"\u2190 {ev[1]}", "rx")
        elif kind == "ack":
            self._handle_ack(ev[1], ev[2])
        elif kind == "data":
            self._handle_data(ev[1])
        elif kind == "timeout":
            self._handle_timeout(ev[1])
        elif kind == "error":
            self._set_message(ev[1], "err")
        elif kind == "disconnected":
            self._on_link_lost(ev[1])

    def _handle_timeout(self, cmd):
        if cmd.upper().startswith("STATUS"):
            self.missed_status += 1
            if self.missed_status == 3:
                self.esp_alive = False
                self._update_status_panel()
                self._set_message("ESP32 is not answering STATUS (check firmware, "
                                  "baud rate and port).", "warn")
        else:
            self._set_message(f"Timeout: no reply to '{cmd}' within "
                              f"{config.ACK_TIMEOUT_S:g} s.", "err")

    def _handle_ack(self, cmd, resp):
        parts = cmd.split(",")
        verb = parts[0].upper()
        sub = parts[1].upper() if len(parts) > 1 else ""
        self.esp_alive = True
        self.missed_status = 0
        if resp.kind == "ERROR":
            text = protocol.describe_error(resp.message)
            self._set_message(f"ESP32 rejected '{cmd}': {text}", "err")
            if verb == "START":
                messagebox.showerror("START rejected", f"The ESP32 answered: {text}")
            self._update_status_panel()
            return
        if verb == "START":
            self._set_state("Running")
            self._set_message("Output running.", "ok")
        elif verb == "STOP":
            self._set_state("Stopped")
            self._set_message("Output stopped.", "ok")
        elif verb == "PAUSE":
            self._set_state("Paused")
        elif verb == "RESUME":
            self._set_state("Running")
        elif verb == "RESET":
            self._set_state("Stopped")
            self.reported, self.measured = {}, {}
            self._set_message("ESP32 reset to defaults.", "ok")
        elif verb in ("CONFIG", "SET"):
            self._set_message("Configuration accepted by ESP32.", "ok")
        elif verb == "SWEEP":
            if sub == "START":
                self._set_sweep(True)
                self._set_message("Sweep started.", "ok")
            elif sub == "STOP":
                self._set_sweep(False)
                self._set_message("Sweep stopped.", "ok")
        self._update_status_panel()

    def _handle_data(self, resp):
        kind = resp.kind
        if kind == "STATUS":
            f = resp.fields
            self.reported.update(f)
            self.esp_alive = True
            self.missed_status = 0
            state = f.get("STATE", "").upper()
            if state in ("RUNNING", "STOPPED", "PAUSED"):
                self._set_state(state.capitalize())
            if "SWEEP" in f:
                self._set_sweep(f["SWEEP"].upper() in ("ON", "RUNNING", "1", "TRUE"))
            self._update_status_panel()
            self._update_monitor()
        elif kind == "MEAS":
            self.measured.update(resp.fields)
            self._update_monitor()
        elif kind in ("RUNNING", "STOPPED", "PAUSED"):
            self._set_state(kind.capitalize())
        elif kind == "READY":
            self.esp_alive = True
            self._set_state("Stopped")
            self._set_message("ESP32 reports READY.", "ok")
            self._update_status_panel()
        elif kind == "ERROR":
            self._set_message("ESP32 error: " + protocol.describe_error(resp.message), "err")
        # OK / UNKNOWN lines are only shown in the log
