# OWNED BY G3 - replace this stub
"""Private ctypes declarations for the win32 package (structures, constants, prototypes).

Port from docs/research/scripts/win32/wa_win32.py (input, clipboard, foreground, IME) and
wb_win32.py (windows, monitors, DPI, tokens). Rules: WinDLL(..., use_last_error=True);
EVERY foreign function gets explicit argtypes AND restype (64-bit handles, GlobalLock
truncation); ULONG_PTR = c_size_t (sizeof(INPUT) must be 40); keep references to ctypes
callbacks; pass POINT by value to WindowFromPoint. Only modules of autopress.win32 import this.
"""

__stub__ = True
