# OWNED BY G3 - replace this stub
"""Win32 layer (G3), ctypes only: input injection, clipboard, windows, DPI, elevation, hotkeys.

Other groups import the public modules (keys, input, clipboard, windows, elevation, dpi,
hotkeys, power) - never ``api`` directly. Importing any module here must not change process state
(no DPI calls, no focus changes, no hooks).
"""
