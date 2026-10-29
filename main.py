"""main.py - start the ESP32 function generator GUI.

    python main.py
"""
import tkinter as tk


def _enable_hidpi():
    """Sharper text on Windows high-DPI displays (no effect elsewhere)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    _enable_hidpi()
    from gui import FunctionGeneratorApp
    root = tk.Tk()
    FunctionGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
