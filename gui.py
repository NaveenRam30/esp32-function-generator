"""gui.py - Tkinter front-end of the ESP32 function generator.

The GUI never talks to the serial port directly: it queues commands in
SerialManager and polls its event queue every 40 ms, so it cannot freeze.
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, MaxNLocator

import calculations
import config
import protocol
import waveform
from config import COLORS as C
from config import GeneratorSettings
from serial_manager import SerialError, SerialManager, list_serial_ports

# Presentation only: hardware defaults and the wire protocol remain in config.py.
C = dict(C, bg="#0b1220", header="#101b2d", panel="#111e30",
         panel2="#1b2c43", hover="#273e58", field="#0b1525",
         border="#2b4059", fg="#edf3fc", dim="#a1b3cb", accent="#65d6ff",
         trace="#60efbe", plot_bg="#091321", grid="#20334a")
FONT_UI = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_MONO = ("Consolas", 11)
FONT_BIG = ("Segoe UI", 22, "bold")
FONT_CHIP = ("Segoe UI", 16, "bold")


# ======================================================================
# Styling
# ======================================================================
def apply_style(root: tk.Tk):
    global FONT_UI, FONT_BOLD, FONT_MONO, FONT_BIG, FONT_CHIP
    families = {name.casefold(): name for name in tkfont.families(root)}
    ui = next((families[name.casefold()] for name in ("Segoe UI", "DejaVu Sans", "Helvetica")
               if name.casefold() in families), tkfont.nametofont("TkDefaultFont").actual("family"))
    mono = next((families[name.casefold()] for name in ("Consolas", "DejaVu Sans Mono", "Courier")
                 if name.casefold() in families), tkfont.nametofont("TkFixedFont").actual("family"))
    FONT_UI, FONT_BOLD = (ui, 10), (ui, 10, "bold")
    FONT_MONO, FONT_BIG, FONT_CHIP = (mono, 11), (ui, 22, "bold"), (ui, 16, "bold")
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
                 padding=(12, 7), borderwidth=0)
    st.map("TButton",
           background=[("active", C["hover"]), ("disabled", C["panel"])],
           foreground=[("disabled", C["dim"])])
    st.configure("TEntry", fieldbackground=C["field"], foreground=C["fg"],
                 insertcolor=C["fg"], padding=(7, 5))
    st.configure("Bad.TEntry", fieldbackground=C["bad_bg"], foreground=C["err"],
                 insertcolor=C["fg"], padding=(7, 5))
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

    st.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 0, 0, 7))
    st.configure("TNotebook.Tab", background=C["header"], foreground=C["dim"],
                 padding=(14, 8), font=FONT_BOLD, borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", C["panel"])],
           foreground=[("selected", C["accent"])])
    st.configure("TCombobox", padding=(6, 5), arrowsize=14)
    st.configure("Primary.TButton", background=C["accent"], foreground=C["bg"], font=FONT_BOLD)
    st.map("Primary.TButton", background=[("active", "#a3e7ff"), ("disabled", C["panel2"])],
           foreground=[("disabled", C["dim"])])
    st.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["bg"],
                 borderwidth=0, arrowsize=12)


def kv_grid(parent, items, ncols=2, start_row=0):
    """Create 'label  value' pairs in a grid; returns {key: value_label}."""
    labels = {}
    for i, (key, text) in enumerate(items):
        r = start_row + i // ncols
        c = (i % ncols) * 2
        ttk.Label(parent, text=text, foreground=C["dim"]).grid(
            row=r, column=c, sticky="w", padx=(6, 4), pady=4)
        lbl = ttk.Label(parent, text="\u2014", font=FONT_MONO)
        lbl.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=4)
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
        # Fit laptop screens; retain the existing Windows high-DPI setup in main.py.
        self.ui_scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(round(1500 * self.ui_scale), sw - 48)
        height = min(round(920 * self.ui_scale), sh - 90)
        root.geometry(f"{width}x{height}+20+20")
        root.minsize(min(round(1100 * self.ui_scale), sw - 48),
                     min(round(680 * self.ui_scale), sh - 90))
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
        return ttk.LabelFrame(parent, text=f" {title} ", padding=10)

    def _build_ui(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(2, weight=1)
        self._focused = False
        self._details_visible = False
        self._build_header()
        self._build_connection(r)

        self.workspace = tk.PanedWindow(r, orient="horizontal", bg=C["bg"],
                                        sashwidth=8, bd=0, sashrelief="flat",
                                        opaqueresize=True)
        self.workspace.grid(row=2, column=0, sticky="nsew", padx=16, pady=(4, 10))
        self.sidebar = tk.Frame(self.workspace, bg=C["bg"])
        self.main_area = tk.Frame(self.workspace, bg=C["bg"])
        self.workspace.add(self.sidebar, minsize=round(395 * self.ui_scale),
                           width=round(440 * self.ui_scale), stretch="never")
        self.workspace.add(self.main_area, minsize=round(600 * self.ui_scale), stretch="always")
        self.main_area.columnconfigure(0, weight=1)
        self.main_area.rowconfigure(0, weight=1)
        self._build_top()
        self._build_preview()
        self._build_summary()
        self._build_details()
        self._build_buttons()
        self.msg_lbl = tk.Label(r, text="Ready. Connect your ESP32 to enable output controls.",
                                anchor="w", bg=C["header"], fg=C["dim"], font=FONT_UI,
                                padx=18, pady=6)
        self.msg_lbl.grid(row=4, column=0, sticky="ew")
        r.bind("<F11>", self._toggle_fullscreen)
        r.bind("<Escape>", self._exit_focus)

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C["header"])
        hdr.grid(row=0, column=0, sticky="ew")
        brand = tk.Frame(hdr, bg=C["header"])
        brand.pack(side="left", padx=18, pady=12)
        tk.Label(brand, text="FUNCTION GENERATOR", bg=C["header"], fg=C["fg"],
                 font=(FONT_UI[0], 19, "bold")).pack(anchor="w")
        tk.Label(brand, text="ESP32  /  Signal control & waveform preview", bg=C["header"],
                 fg=C["dim"], font=FONT_UI).pack(anchor="w", pady=(2, 0))
        self.hdr_state = tk.Label(hdr, text="● DISCONNECTED", bg=C["header"],
                                  fg=C["err"], font=FONT_BOLD)
        self.hdr_state.pack(side="right", padx=20)
        self.state_lbl = tk.Label(hdr, text="OFFLINE", bg=C["header"],
                                  fg=C["dim"], font=FONT_BOLD)
        self.state_lbl.pack(side="right", padx=18)

    def _scroll_page(self, notebook, title):
        """Keep controls reachable when the window or display is small."""
        page = tk.Frame(notebook, bg=C["bg"])
        notebook.add(page, text=title)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        canvas = tk.Canvas(page, bg=C["bg"], bd=0, highlightthickness=0, width=1)
        bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=C["bg"])
        inner.columnconfigure(0, weight=1)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        # Local bindings avoid stealing mouse-wheel input from other panels.
        def wheel(event):
            if inner.winfo_reqheight() <= canvas.winfo_height():
                return
            if getattr(event, "num", None) in (4, 5):
                step = -1 if event.num == 4 else 1
            else:
                step = -1 if event.delta > 0 else 1
            canvas.yview_scroll(step * 3, "units")
            return "break"
        def bind_children(widget):
            if not isinstance(widget, (ttk.Combobox, ttk.Scale)):
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(sequence, wheel, add="+")
            for child in widget.winfo_children():
                bind_children(child)
        self.root.after_idle(lambda: bind_children(page))
        return inner

    def _build_top(self):
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(1, weight=1)
        tk.Label(self.sidebar, text="SIGNAL SETTINGS", bg=C["bg"], fg=C["dim"],
                 font=FONT_BOLD, anchor="w").grid(row=0, column=0, sticky="ew", pady=(2, 10))
        self.settings_tabs = ttk.Notebook(self.sidebar)
        self.settings_tabs.grid(row=1, column=0, sticky="nsew")
        signal = self._scroll_page(self.settings_tabs, "Signal")
        sweep = self._scroll_page(self.settings_tabs, "Sweep")
        hardware = self._scroll_page(self.settings_tabs, "Output stage")
        self._build_config(signal)
        self._build_presets(signal)
        self._build_sweep(sweep)
        self._build_hardware(hardware)
        ttk.Label(hardware, text="The amber dashed lines in the preview mark the selected "
                  "output limits. Orange traces indicate a requested signal beyond those limits.",
                  foreground=C["dim"], wraplength=340).grid(row=2, column=0, sticky="ew", padx=12, pady=12)

    def _build_connection(self, parent):
        p = tk.Frame(parent, bg=C["bg"])
        self.connection_bar = p
        p.grid(row=1, column=0, sticky="ew", padx=18, pady=(10, 12))
        p.columnconfigure(1, weight=1)
        tk.Label(p, text="SERIAL PORT", bg=C["bg"], fg=C["dim"], font=FONT_BOLD).grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(p, textvariable=self.port_var, width=28, state="readonly")
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(p, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=(0, 16))
        tk.Label(p, text="BAUD", bg=C["bg"], fg=C["dim"], font=FONT_BOLD).grid(row=0, column=3)
        self.baud_var = tk.StringVar(value=str(config.DEFAULT_BAUD))
        ttk.Combobox(p, textvariable=self.baud_var, width=8, state="readonly",
                     values=[str(b) for b in config.BAUD_RATES]).grid(row=0, column=4, padx=8)
        self.btn_connect = ttk.Button(p, text="Connect", style="Primary.TButton", command=self.on_connect)
        self.btn_connect.grid(row=0, column=5, padx=(8, 6))
        self.btn_disconnect = ttk.Button(p, text="Disconnect", command=self.on_disconnect)
        self.btn_disconnect.grid(row=0, column=6)

    def _build_presets(self, parent):
        p = self._panel(parent, "Quick presets")
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
        p = self._panel(parent, "Frequency sweep")
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
        p = self._panel(parent, "Waveform parameters")
        p.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        p.columnconfigure(3, weight=1, minsize=70)

        ttk.Label(p, text="Waveform").grid(row=1, column=0, sticky="w", padx=(6, 8), pady=4)
        self.wave_var = tk.StringVar(value="Sine")
        self.wave_combo = ttk.Combobox(p, textvariable=self.wave_var, width=12,
                                       values=config.WAVEFORMS, state="readonly")
        self.wave_combo.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        self.wave_combo.bind("<<ComboboxSelected>>", lambda e: self._on_wave_change())

        lo, hi = config.OUTPUT_MODES[config.DEFAULT_OUTPUT_MODE]
        cb = self._on_param_change
        self.freq = FreqControl(p, 2, cb)
        self.vpp = ParamControl(p, 3, "Amplitude", "Vpp", config.VPP_MIN,
                                config.VPP_MAX, 2.0, 2, cb)
        self.offset = ParamControl(p, 4, "DC Offset", "V", lo, hi, 1.0, 2, cb)
        self.phase = ParamControl(p, 5, "Phase", "\u00b0", config.PHASE_MIN,
                                  config.PHASE_MAX, 0.0, 0, cb)
        ttk.Button(p, text="Reset phase", command=self._reset_phase).grid(
            row=10, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))
        self.duty = ParamControl(p, 6, "Duty Cycle", "%", config.DUTY_MIN,
                                 config.DUTY_MAX, 50.0, 0, cb)

        ttk.Label(p, text=("Vpp = peak-to-peak (the controlled value).  Peak = Vpp/2.  "
                           "RMS depends on the waveform (see Output details)."),
                  foreground=C["dim"], wraplength=340).grid(
            row=7, column=0, columnspan=5, sticky="w", padx=6, pady=(4, 0))
        self.expected_lbl = ttk.Label(p, text="", font=FONT_BOLD, wraplength=340)
        self.expected_lbl.grid(row=8, column=0, columnspan=5, sticky="w", padx=6, pady=2)
        self.error_lbl = ttk.Label(p, text="", foreground=C["err"], wraplength=340)
        self.error_lbl.grid(row=9, column=0, columnspan=5, sticky="w", padx=6)

    def _build_hardware(self, parent):
        p = self._panel(parent, "Hardware output limits")
        p.grid(row=1, column=0, sticky="ew", pady=6)
        p.columnconfigure(1, weight=1)
        ttk.Label(p, text="Output configuration").grid(row=0, column=0, sticky="w", padx=6)
        self.out_mode_var = tk.StringVar(value=config.DEFAULT_OUTPUT_MODE)
        cb = ttk.Combobox(p, textvariable=self.out_mode_var, state="readonly",
                          values=list(config.OUTPUT_MODES), width=34)
        cb.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 10))
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_output_mode())
        ttk.Label(p, text=config.HW_LIMIT_MESSAGE, foreground=C["dim"],
                  wraplength=340).grid(row=2, column=0, columnspan=2, sticky="w",
                                       padx=6, pady=2)
        self.warn_lbl = ttk.Label(p, text="", wraplength=340, font=FONT_BOLD)
        self.warn_lbl.grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=2)

    # ---------------------------------------------------- right column
    def _build_esp_status(self, parent):
        p = ttk.Frame(parent, padding=10)
        p.grid(row=0, column=0, sticky="nsew")
        self.st = kv_grid(p, [
            ("conn", "Link"), ("port", "Port"), ("wave", "Waveform"),
            ("freq", "Frequency"), ("vpp", "Amplitude"), ("phase", "Phase"),
            ("state", "Output"), ("fs", "Sample rate"), ("samples", "Samples"),
            ("fw", "Firmware"),
        ], ncols=3)
        self.conn_status = ttk.Label(p, text="● Disconnected", foreground=C["err"], font=FONT_BOLD)
        self.conn_status.grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))
        self.conn_port = ttk.Label(p, text="Port: —", foreground=C["dim"])
        self.conn_port.grid(row=4, column=2, columnspan=4, sticky="w", padx=6, pady=(6, 0))

    def _build_output_info(self, parent):
        p = ttk.Frame(parent, padding=10)
        p.grid(row=0, column=0, sticky="nsew")
        self.info = kv_grid(p, [
            ("wave", "Waveform"), ("freq", "Frequency"), ("vpp", "Vpp"),
            ("peak", "Peak"), ("rms_ac", "RMS (AC)"), ("rms_tot", "RMS (total)"),
            ("offset", "DC offset"), ("phase", "Phase"), ("duty", "Duty"),
            ("vmin", "Min voltage"), ("vmax", "Max voltage"),
        ], ncols=3)

    def _build_monitor(self, parent):
        p = ttk.Frame(parent, padding=10)
        p.grid(row=0, column=0, sticky="nsew")
        for c, h in enumerate(["Parameter", "Configured (PC)", "Reported (ESP32)", "Measured"]):
            p.columnconfigure(c, weight=1)
            ttk.Label(p, text=h, foreground=C["dim"], font=FONT_BOLD).grid(
                row=0, column=c, sticky="w", padx=6, pady=(0, 10))
        self.mon = {}
        for r, (key, name) in enumerate([("freq", "Frequency"), ("state", "Output state"),
                                         ("dac", "DAC level"), ("fs", "Sample rate")], 1):
            ttk.Label(p, text=name).grid(row=r, column=0, sticky="w", padx=6, pady=4)
            cells = []
            for c in (1, 2, 3):
                lbl = ttk.Label(p, text="—", font=FONT_MONO)
                lbl.grid(row=r, column=c, sticky="w", padx=6, pady=4)
                cells.append(lbl)
            self.mon[key] = cells

    def _build_details(self):
        # Keep diagnostics in a separate non-modal window so they never squeeze the trace.
        self.details_window = tk.Toplevel(self.root)
        self.details_window.withdraw()
        self.details_window.title("Function generator — Details & serial log")
        self.details_window.configure(bg=C["bg"])
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.details_window.geometry(f"{min(round(1100 * self.ui_scale), sw - 80)}x"
                                     f"{min(round(380 * self.ui_scale), sh - 120)}+40+80")
        self.details_window.minsize(min(700, sw - 80), min(280, sh - 120))
        self.details_window.protocol("WM_DELETE_WINDOW", self._toggle_details)
        self.details_window.columnconfigure(0, weight=1)
        self.details_window.rowconfigure(0, weight=1)
        self.details_frame = tk.Frame(self.details_window, bg=C["bg"], padx=12, pady=12)
        self.details_frame.grid(row=0, column=0, sticky="nsew")
        self.details_frame.columnconfigure(0, weight=1)
        self.details_frame.rowconfigure(0, weight=1)
        self.details_tabs = ttk.Notebook(self.details_frame)
        self.details_tabs.grid(row=0, column=0, sticky="nsew")
        for title, builder in [("Output details", self._build_output_info),
                               ("Device status", self._build_esp_status),
                               ("Monitoring", self._build_monitor), ("Serial log", self._build_log)]:
            # Horizontal overflow is scrollable for long device/measurement fields.
            page = tk.Frame(self.details_tabs, bg=C["panel"])
            page.columnconfigure(0, weight=1)
            page.rowconfigure(0, weight=1)
            self.details_tabs.add(page, text=title)
            if title == "Serial log":
                builder(page)
                continue
            view = tk.Canvas(page, bg=C["panel"], highlightthickness=0, width=1, height=1)
            view.grid(row=0, column=0, sticky="nsew")
            xs = ttk.Scrollbar(page, orient="horizontal", command=view.xview)
            ys = ttk.Scrollbar(page, orient="vertical", command=view.yview)
            xs.grid(row=1, column=0, sticky="ew")
            ys.grid(row=0, column=1, sticky="ns")
            view.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
            inner = ttk.Frame(view)
            inner.columnconfigure(0, weight=1)
            inner.rowconfigure(0, weight=1)
            builder(inner)
            window = view.create_window((0, 0), window=inner, anchor="nw")
            inner.bind("<Configure>", lambda e, v=view: v.configure(scrollregion=v.bbox("all")))
            view.bind("<Configure>", lambda e, v=view, w=window, i=inner:
                      v.itemconfigure(w, width=max(e.width, i.winfo_reqwidth())))

    def _build_preview(self):
        self.preview_frame = tk.Frame(self.main_area, bg=C["panel"],
                                      highlightbackground=C["border"], highlightthickness=1)
        frame = self.preview_frame
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        heading = tk.Frame(frame, bg=C["panel"])
        heading.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 0))
        tk.Label(heading, text="WAVEFORM PREVIEW", bg=C["panel"], fg=C["fg"],
                 font=FONT_BOLD).pack(side="left")
        self.focus_button = ttk.Button(heading, text="Focus preview", command=self._toggle_focus)
        self.focus_button.pack(side="right")
        readouts = tk.Frame(frame, bg=C["panel"])
        readouts.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 0))
        self.big_freq = ttk.Label(readouts, text="", font=FONT_BIG, foreground=C["accent"])
        self.big_freq.pack(side="left", padx=(0, 26))
        self.big_vpp = ttk.Label(readouts, text="", font=FONT_BIG, foreground=C["trace"])
        self.big_vpp.pack(side="left")
        self.preview_wave_lbl = ttk.Label(readouts, text="SINE", foreground=C["dim"], font=FONT_BOLD)
        self.preview_wave_lbl.pack(side="right")

        self.fig = Figure(figsize=(9, 5.6), dpi=100, facecolor=C["panel"])
        self.ax = self.fig.add_subplot(111)
        ax = self.ax
        ax.set_facecolor(C["plot_bg"])
        ax.set_axisbelow(True)
        ax.grid(True, color=C["grid"], linewidth=0.9)
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
        ax.grid(True, which="minor", color=C["grid"], linewidth=0.5, alpha=0.45)
        for spine in ax.spines.values():
            spine.set_color(C["border"])
        ax.tick_params(colors=C["dim"], labelsize=10, pad=7)
        ax.tick_params(which="minor", colors=C["border"])
        ax.xaxis.label.set_color(C["dim"])
        ax.yaxis.label.set_color(C["dim"])
        ax.set_ylabel("Voltage (V)", fontsize=10, labelpad=10)
        self.line, = ax.plot([], [], color=C["trace"], linewidth=2.6,
                             solid_capstyle="round", label="Configured waveform")
        self.hw_lines = [
            ax.axhline(0, color=C["warn"], linestyle=(0, (5, 5)), linewidth=1.1, alpha=0.8),
            ax.axhline(3.3, color=C["warn"], linestyle=(0, (5, 5)), linewidth=1.1, alpha=0.8),
        ]
        self.fig.subplots_adjust(left=0.10, right=0.975, top=0.95, bottom=0.15)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        plot_widget = self.canvas.get_tk_widget()
        plot_widget.configure(width=1, height=1, highlightthickness=0)
        plot_widget.grid(row=2, column=0, sticky="nsew", padx=4)
        self.canvas.mpl_connect("resize_event", self._resize_plot)
        plot_widget.bind("<Map>", lambda e: self.root.after_idle(self._resize_plot), add="+")
        toolbar = tk.Frame(frame, bg=C["panel"])
        toolbar.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 10))
        ttk.Label(toolbar, text="Cycles", foreground=C["dim"]).pack(side="left")
        self.preview_cycles = tk.StringVar(value="4")
        cycles = ttk.Combobox(toolbar, textvariable=self.preview_cycles, values=["2", "4", "8"],
                              state="readonly", width=2)
        cycles.pack(side="left", padx=(6, 16))
        cycles.bind("<<ComboboxSelected>>", lambda e: self._schedule_refresh())
        ttk.Label(toolbar, text="Scale", foreground=C["dim"]).pack(side="left")
        self.preview_scale = tk.StringVar(value="Fit waveform")
        scale = ttk.Combobox(toolbar, textvariable=self.preview_scale,
                             values=["Fit waveform", "Hardware range"], state="readonly", width=16)
        scale.pack(side="left", padx=6)
        scale.bind("<<ComboboxSelected>>", lambda e: self._schedule_refresh())
        ttk.Label(toolbar, text="- -  Hardware limits", foreground=C["warn"]).pack(side="right")
        self.preview_note = tk.Label(frame, text="Software estimate | not a measured signal",
                                     bg=C["panel"], fg=C["dim"], font=FONT_UI, anchor="w")
        self.preview_note.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.preview_note.bind("<Configure>", lambda e:
                               e.widget.configure(wraplength=max(180, e.width - 4)))

    def _resize_plot(self, event=None):
        """Fit the actual Tk canvas, including fractional Windows/Linux DPI scaling."""
        widget = self.canvas.get_tk_widget()
        w, h = max(widget.winfo_width(), 1), max(widget.winfo_height(), 1)
        self.fig.set_size_inches(w / self.fig.dpi, h / self.fig.dpi, forward=False)
        self.fig.subplots_adjust(left=min(0.20, 76 / w), right=1 - min(0.05, 22 / w),
                                 bottom=min(0.30, 52 / h), top=1 - min(0.08, 18 / h))
        self.canvas.draw_idle()

    def _build_summary(self):
        f = tk.Frame(self.main_area, bg=C["bg"])
        self.summary_frame = f
        f.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.chips = {}
        for i, (key, title) in enumerate([("vpp", "AMPLITUDE / Vpp"), ("rms", "RMS / AC"),
                                          ("offset", "DC OFFSET"), ("phase", "PHASE"),
                                          ("freq", "FREQUENCY"), ("duty", "DUTY")]):
            f.columnconfigure(i, weight=1, uniform="chip")
            chip = tk.Frame(f, bg=C["panel"], highlightbackground=C["border"], highlightthickness=1)
            chip.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0))
            tk.Label(chip, text=title, bg=C["panel"], fg=C["dim"],
                     font=(FONT_UI[0], 8, "bold")).pack(pady=(10, 2))
            lbl = tk.Label(chip, text="—", bg=C["panel"], fg=C["fg"], font=FONT_CHIP)
            lbl.pack(fill="x", pady=(0, 10))
            chip.bind("<Configure>", lambda e, label=lbl: self._fit_readout(label, e.width))
            self.chips[key] = lbl

    def _fit_readout(self, label, width):
        font = tkfont.Font(family=FONT_UI[0], size=16, weight="bold")
        for size in range(16, 9, -1):
            font.configure(size=size)
            if font.measure(label.cget("text")) <= width - 12:
                break
        label.configure(font=(FONT_UI[0], size, "bold"))

    def _build_buttons(self):
        f = tk.Frame(self.root, bg=C["bg"])
        f.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.ctrl_buttons = []
        specs = [("START", C["ok"], self.on_start), ("STOP", C["err"], self.on_stop),
                 ("PAUSE", C["warn"], self.on_pause), ("RESET", "#b4c4da", self.on_reset)]
        for i, (text, color, cmd) in enumerate(specs):
            b = tk.Button(f, text=text, command=cmd, bg=color, fg=C["bg"],
                          activebackground=color, disabledforeground=C["dim"],
                          font=FONT_BOLD, width=10, padx=8, pady=12, relief="flat",
                          bd=0, cursor="hand2", highlightthickness=0)
            b.grid(row=0, column=i, sticky="ew", padx=(0, 8))
            self.ctrl_buttons.append((b, color))
        self.btn_start, self.btn_stop, self.btn_pause, self.btn_reset = (b for b, _ in self.ctrl_buttons)
        f.columnconfigure(4, weight=1)
        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Live update while running", variable=self.live_var,
                        style="Root.TCheckbutton").grid(row=0, column=4, sticky="w", padx=12)
        self.details_button = ttk.Button(f, text="Show details & log", command=self._toggle_details)
        self.details_button.grid(row=0, column=5, sticky="e")

    def _toggle_details(self):
        if self._focused:
            self._toggle_focus()
        self._details_visible = not self._details_visible
        self._show_details()

    def _show_details(self):
        if self._details_visible:
            self.details_window.deiconify()
            self.details_window.lift()
        else:
            self.details_window.withdraw()
        self.details_button.configure(text="Hide details & log" if self._details_visible else "Show details & log")

    def _toggle_focus(self):
        self._focused = not self._focused
        if self._focused:
            self._sidebar_width = self.sidebar.winfo_width()
            self.workspace.forget(self.sidebar)
            self.connection_bar.grid_remove()
            self.summary_frame.grid_remove()
            self.details_window.withdraw()
        else:
            self.workspace.add(self.sidebar, before=self.main_area,
                               minsize=round(395 * self.ui_scale),
                               width=self._sidebar_width, stretch="never")
            self.connection_bar.grid()
            self.summary_frame.grid()
            self._show_details()
        self.focus_button.configure(text="Restore workspace" if self._focused else "Focus preview")

    def _toggle_fullscreen(self, event=None):
        self.root.attributes("-fullscreen", not bool(self.root.attributes("-fullscreen")))
        return "break"

    def _exit_focus(self, event=None):
        self.root.attributes("-fullscreen", False)
        if self._focused:
            self._toggle_focus()
        return "break"

    def _build_log(self, parent):
        f = ttk.Frame(parent, padding=8)
        f.grid(row=0, column=0, sticky="nsew")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        self.log = tk.Text(f, height=5, bg=C["field"], fg=C["fg"], bd=0,
                           highlightthickness=0, font=(FONT_MONO[0], 10),
                           state="disabled", wrap="none", padx=10, pady=6)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.log.yview)
        xs = ttk.Scrollbar(f, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=sb.set, xscrollcommand=xs.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        for tag, color in [("tx", C["accent"]), ("rx", C["fg"]), ("info", C["dim"]),
                           ("ok", C["ok"]), ("warn", C["warn"]), ("err", C["err"])]:
            self.log.tag_configure(tag, foreground=color)

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

        for label in self.chips.values():
            if label.master.winfo_width() > 1:
                self._fit_readout(label, label.master.winfo_width())

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
        t, v, unit, scale = waveform.preview(s, cycles=int(self.preview_cycles.get()))
        self.line.set_data(t * scale, v)
        self.line.set_color(C["warn"] if warnings else C["trace"])
        self.ax.set_xlim(0, t[-1] * scale)
        if self.preview_scale.get() == "Hardware range":
            ymin, ymax = min(lo, hw_lo), max(hi, hw_hi)
        else:
            ymin, ymax = lo, hi
        pad = max(0.10, 0.15 * (ymax - ymin))
        self.ax.set_ylim(ymin - pad, ymax + pad)
        self.hw_lines[0].set_ydata([hw_lo, hw_lo])
        self.hw_lines[1].set_ydata([hw_hi, hw_hi])
        self.ax.set_xlabel(f"Time ({unit})")
        self.preview_wave_lbl.configure(text=s.wave.upper())
        note = "Software estimate | not a measured signal"
        if warnings:
            note += "  |  Requested output exceeds hardware limits"
        elif self._errors():
            note += "  |  Showing the last valid settings"
        self.preview_note.configure(text=note, fg=C["warn"] if warnings else C["dim"])
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
