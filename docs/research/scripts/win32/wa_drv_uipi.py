"""wa_drv_uipi.py - Test 7: UIPI. Elevating would need a UAC prompt, so the same mechanism is shown one
level down: a LOW-integrity copy of this process (CreateProcessAsUserW with a duplicated token labelled
S-1-16-4096) injects into the MEDIUM-integrity target, which is exactly "lower IL -> higher IL" as with a
normal AutoPress -> elevated game. Control: the same child at medium IL.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_uipi.py
Output: wa_results/wa_result_uipi.json
"""
import ctypes
import ctypes.wintypes as W
import subprocess
import sys
import time

import wa_harness as h
import wa_win32 as w

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", W.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE),
                ("hStdError", W.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


advapi32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
advapi32.OpenProcessToken.restype = W.BOOL
advapi32.DuplicateTokenEx.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.POINTER(W.HANDLE)]
advapi32.DuplicateTokenEx.restype = W.BOOL
advapi32.ConvertStringSidToSidW.argtypes = [W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.ConvertStringSidToSidW.restype = W.BOOL
advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
advapi32.GetLengthSid.restype = W.DWORD
advapi32.SetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
advapi32.SetTokenInformation.restype = W.BOOL
advapi32.CreateProcessAsUserW.argtypes = [W.HANDLE, W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL,
                                          W.DWORD, ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                          ctypes.POINTER(PROCESS_INFORMATION)]
advapi32.CreateProcessAsUserW.restype = W.BOOL
kernel32.GetCurrentProcess.restype = W.HANDLE
kernel32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel32.WaitForSingleObject.restype = W.DWORD
kernel32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
kernel32.GetExitCodeProcess.restype = W.BOOL
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def run_low_il(cmdline, cwd):
    tok, new = W.HANDLE(), W.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x1 | 0x2 | 0x8 | 0x80, ctypes.byref(tok)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not advapi32.DuplicateTokenEx(tok, 0, None, 2, 1, ctypes.byref(new)):     # SecurityImpersonation, TokenPrimary
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.c_void_p()
    advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid))            # Low Mandatory Level
    tml = TOKEN_MANDATORY_LABEL(SID_AND_ATTRIBUTES(sid, 0x20))                   # SE_GROUP_INTEGRITY
    if not advapi32.SetTokenInformation(new, 25, ctypes.byref(tml),                # TokenIntegrityLevel
                                        ctypes.sizeof(tml) + advapi32.GetLengthSid(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    si = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW))
    pi = PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmdline)
    if not advapi32.CreateProcessAsUserW(new, None, buf, None, None, False, 0x08000000, None, cwd,  # CREATE_NO_WINDOW
                                         ctypes.byref(si), ctypes.byref(pi)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32.WaitForSingleObject(pi.hProcess, 20000)
    code = W.DWORD()
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    for hh in (pi.hProcess, pi.hThread, tok, new):
        kernel32.CloseHandle(hh)
    kernel32.LocalFree(sid)
    return code.value


def decode(code):
    return {"guard_ok": bool(code & 1), "sendinput_ret": (code >> 1) & 0xFF, "sendinput_err": (code >> 9) & 0xFFF,
            "postmessage_ok": bool((code >> 21) & 1), "postmessage_err": (code >> 22) & 0x1FF, "raw": code}


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag()}
    child = str(h.HERE / "wa_uipi_child.py")
    t = h.Target("uipi", extra=["--ime", "off"])
    try:
        for label in ("low_il", "medium_il_control"):
            out["ensure_fg_" + label] = h.ensure_foreground(t)
            m = t.mark()
            if label == "low_il":
                code = run_low_il(f'"{h.PY}" "{child}" {hex(t.hwnd)}', str(h.HERE))
            else:
                code = subprocess.run([h.PY, child, hex(t.hwnd)], cwd=str(h.HERE)).returncode
            time.sleep(0.4)
            r = decode(code)
            r["target_text_after"] = t.last_text()
            r["target_key_events"] = len([e for e in t.since(m) if e["ev"] in ("key", "text")])
            out[label] = r
            print(label, r, flush=True)
            if t.last_text():
                mm = t.mark()
                w.clear_field(w.Guard(t.hwnd))
                t.wait_text("", mm, 0.6, 0.15)
    finally:
        h.release_safety()
        t.close()
    print("saved", h.save_result("uipi", out))


if __name__ == "__main__":
    sys.exit(main())
