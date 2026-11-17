# R2b: DPI coordinates, window management, elevation and screen capture

Verified 2026-11-17 on Windows 10 LTSC 21H2 (19044), Python 3.12.10, PyQt6 6.12.1 / Qt 6.12.0, mss 10.2.0,
numpy 2.5.5, Pillow 13.0.0. Two 1920x1080 monitors at 100 %: primary at (0,0), secondary at (-1920,0).
All code is ctypes only, and every foreign function declares argtypes and restype. Toward other apps the scripts only
read state. My own test windows never took focus, were input-transparent where possible, avoided other agents' windows
and the cursor, and were on screen for at most 1.3 s. The foreground window was checked unchanged after every visible
test. **No screenshot was written to disk.** Scripts are in `scripts/win32/`; raw JSON stayed in the session scratch dir.

| Script | Measures |
|---|---|
| `wb_win32.py` | shared bindings + helpers (importing it changes nothing: no DPI or focus change) |
| `wb_run_suite.py` runs `wb_qt_probe.py` | awareness vs import order, QScreen vs monitors, mapping, overlay math, capture, threads |
| `wb_windows_probe.py` | enumeration, rects, hit-testing, re-finding, IsWindow, token elevation/integrity survey |
| `wb_capture_timing.py` | mss timings, numpy/PIL conversions, worker-thread DPI awareness |
| `wb_exe_manifest.py` | embedded manifests of python.exe and of a PyInstaller 6.22.3 exe (read without running) |
| `wb_coords.py` | profile coordinate helpers; self-test = 36,502 math checks + a live hidden-window check |

High and mixed DPI were **emulated** with `QT_SCALE_FACTOR` (1.25/1.5/1.75) and `QT_SCREEN_SCALE_FACTORS=1.5;1.25`.
This tests Qt's coordinate math against real HWND/mss pixels, but not Windows' own 125/150 % scaling (see Open issues).
Qt advises against these variables in production [Q1].

## 0. Recommendations
1. Create `QApplication` **before** `mss.MSS()` or any DPI-dependent call. The process then becomes Per-Monitor-Aware V2
   (PMv2), and every Win32 and mss coordinate is a physical pixel ("raw pixels of each display" [M3]).
2. Use physical pixels everywhere: target windows, profiles, capture and input. Use Qt logical coordinates only to draw
   AutoPress's own UI (section 1).
3. Picker: one frozen-screenshot overlay per QScreen. Convert clicks with `monitor_origin + qRound(event.position()*dpr)`
   or read `GetCursorPos()`. Hide the overlays before calling `WindowFromPoint` (section 5).
4. Profiles: store points and regions relative to the target's client area, as offsets *and* ratios (section 6).
5. Elevation: compare token integrity levels before a run. If the target's level is higher, block the run and offer
   "restart as administrator", because UIPI drops input silently (section 3).
6. Capture with `mss.MSS()` (not the deprecated `mss.mss()`), one instance per worker thread. `np.asarray(shot)` gives a
   zero-copy BGRA array. Keep `QScreen.grabWindow` on the GUI thread.

## 1. DPI awareness and logical/physical mapping
| Sequence (`wb_run_suite.py` import/before/after/base; `wb_capture_timing.py`) | Before Qt | After `QApplication` |
|---|---|---|
| python.exe alone (its manifest has no dpiAware entry: `wb_exe_manifest.py`) | UNAWARE | – |
| `import mss`, then Qt (the import changes nothing) | UNAWARE | **PMv2** |
| `mss.MSS()` **before** `QApplication` | PMv1 | **stays PMv1**; Qt warns `SetProcessDpiAwarenessContext() failed: Access is denied` (localized) |
| `mss.MSS()` after `QApplication` | – | PMv2; mss's `SetProcessDpiAwareness(2)` returns 0x80070005, which mss ignores |
| QThread / threading.Thread workers | – | PMv2 (they inherit the process default) |

Cause: every MSS constructor calls `SetProcessDpiAwareness(2)` (PMv1) (`mss/windows/gdi.py:247-259`), and the process
default can be set only once [M2]. "Qt 6 is Per-Monitor DPI Aware V2 by default" [Q1]; PMv1 is "very limited" [M3].
A PyInstaller 6.22.3 onefile exe has no dpiAware entry and is `asInvoker` (`wb_exe_manifest.py`), so a packaged build
also gets PMv2. A Qt-less helper process should call `SetProcessDpiAwarenessContext(-4)` itself.

| QScreen per variant (`wb_qt_probe.py` "screens") | primary (Win32 0,0,1920x1080, 96 dpi) | secondary (Win32 -1920,0,1920x1080, 96 dpi) |
|---|---|---|
| default | (0,0,1920x1080) dpr 1 | (-1920,0,1920x1080) dpr 1 |
| QT_SCALE_FACTOR 1.25 / 1.5 / 1.75 | (0,0,1536x864) / (0,0,1280x720) / (0,0,1097x617) | (-1920,0, same sizes) |
| QT_SCREEN_SCALE_FACTORS=1.5;1.25 | (0,0,1280x720) dpr 1.5 | (-1920,0,1536x864) dpr 1.25 |

In every variant the top-left equals the native origin and `qRound(size*dpr)` equals the Win32 size. Logical space is
therefore "islands of screens" [Q1]: under mixed factors, `screenAt()` returned None for x in [-384,0) and at x=1280.
`QScreen.name()` is the EDID model name plus " (1)", not `\\.\DISPLAYn` ("not guaranteed to match ... native APIs" [Q2]),
so match QScreen to monitor **by native origin**.

Mapping check: a hidden native window at `screen.topLeft()+(101,67)` with a `WA_NativeWindow` child at (37,23).
`mapToGlobal` was compared with `ClientToScreen` of each HWND (`wb_qt_probe.py` "mapping"; 22/22 window cases =
11 runs x 2 screens, position and size OK):

| Variant / screen | logical | measured phys | origin+(L-origin)*dpr | naive L*dpr |
|---|---|---|---|---|
| 1.25 secondary | (-1819,67) | (-1794,84) | (-1793.75,83.75) | (-2273.75,83.75) |
| 1.5 secondary | (-1819,67) | (-1768,101) | (-1768.5,100.5) | (-2728.5,100.5) |
| 1.75 secondary | (-1819,67) | (-1743,117) | (-1743.25,117.25) | (-3183.25,117.25) |
| mixed: secondary 1.25 / primary 1.5 | (-1819,67) / (101,67) | (-1794,84) / (152,101) | (-1793.75,83.75) / (151.5,100.5) | – |
| 1.5, child (global logical) | (138,90) | (208,136) | (207,135): **off by 1** | – |

The claim holds: Qt keeps each screen's origin in native pixels and scales only within the screen. The exact model
(matches every measurement): `win = origin + qRound((L-origin)*dpr)`, `child = parent_client + qRound(local*dpr)`,
`size = qRound(size*dpr)`. qRound rounds half up; Python's `round()` rounds half to even.
The two roundings add up, so for widget points use `ClientToScreen(top_hwnd) + qRound(widget.mapTo(top, p)*dpr)`.
`QCursor.pos()` is an integer logical point: compared with `GetCursorPos()` it was off by 0.5 px at 1.25/1.5 and by
(-0.5, 0.75) at 1.75. Use `GetCursorPos()` when the physical position must be exact.
```python
# verified (wb_win32.py:25-57,112-127): compare DPI contexts, never raw handle values
user32 = ctypes.WinDLL("user32", use_last_error=True); CTX = wt.HANDLE
user32.GetThreadDpiAwarenessContext.restype, user32.GetThreadDpiAwarenessContext.argtypes = CTX, []
user32.AreDpiAwarenessContextsEqual.restype, user32.AreDpiAwarenessContextsEqual.argtypes = wt.BOOL, [CTX, CTX]
is_pmv2 = bool(user32.AreDpiAwarenessContextsEqual(user32.GetThreadDpiAwarenessContext(), CTX(-4)))
```

## 2. Window utilities (`wb_windows_probe.py`)
* **Listing** (`wb_win32.list_top_windows`). EnumWindows, keeping windows that are visible, not DWM-cloaked
  (`DWMWA_CLOAKED`=14 hides suspended UWP windows [M7]), titled, and not `WS_EX_TOOLWINDOW` unless `WS_EX_APPWINDOW`.
  The pid comes from GetWindowThreadProcessId. The exe comes from `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
  `QueryFullProcessImageNameW`. 8-9 windows were listed (Electron, Chrome, Remote Desktop, Qt 6, UWP, Unity games), and
  the exe lookup failed for none. A dev run appears as the **base** `Python312\python.exe`, because the venv python.exe
  is a launcher stub.
* **Pick a window:** `WindowFromPoint(POINT by value)` + `GetAncestor(GA_ROOT=2)`. Over a Qt native child it returns the
  child, and GA_ROOT gives the top-level. Over alien widgets it returns the top-level. Over the taskbar it returns
  `MSTaskListWClass` with root `Shell_TrayWnd`. An input-transparent window is **skipped** (the window below is returned).
  Qt's `Tool|Frameless|StaysOnTop|WindowDoesNotAcceptFocus|WindowTransparentForInput` measured as exstyle 0x080800A8 =
  NOACTIVATE|LAYERED|TOOLWINDOW|TRANSPARENT|TOPMOST. Hidden and disabled windows are never returned [M5].
* **Rects** (physical under PMv2):

| Window | GetWindowRect | DWMWA_EXTENDED_FRAME_BOUNDS | client (GetClientRect + ClientToScreen) |
|---|---|---|---|
| own framed Qt window | (-1868,828,336,159) | (-1861,828,322,152) | (-1860,859,320,120) |
| maximized Electron window | (-8,-8,1936,1056) | (0,0,1920,1040) | (0,0,1920,1040) |
| minimized windows | (-32000,-32000,160,28) | garbage near -32000 | garbage |

  GetWindowRect includes the invisible 7-8 px resize borders, and DWM bounds include the 1 px visible border. Qt's
  `frameGeometry()` was (-1860,828,320,151), which leaves out that 1 px. Base clicks and regions on the **client rect**.
  For an iconic window, the restored rect is `GetWindowPlacement().rcNormalPosition` (showCmd=2), in **workspace**
  coordinates [M6].
* **State and re-finding.** `IsWindowVisible` was False before show, True when shown, False after hide. `IsWindow` was
  True after hide and False after the widget was deleted. Handles are recycled [M4], so treat a target as alive only if
  `IsWindow` holds **and** the pid, exe and class are unchanged. `find_window(exe, title_regex)` found the own window by
  `("python.exe", r"^wb_probe_find_me$")` and returned None after it was deleted. Also store the class name: many games
  use generic titles.
* **Foreign DPI awareness** (`GetWindowDpiAwarenessContext` works cross-process): Electron apps are PMv1; Chrome, Remote
  Desktop, Qt 6 apps and the UWP frame are PMv2. Unaware targets are bitmap-stretched above 100 % [M3]; not observable here.
```python
# verified declarations (wb_win32.py:25,38-100)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)          # keep the callback object referenced
user32.EnumWindows.argtypes, user32.EnumWindows.restype = [WNDENUMPROC, wt.LPARAM], wt.BOOL
user32.WindowFromPoint.argtypes, user32.WindowFromPoint.restype = [wt.POINT], wt.HWND
user32.GetAncestor.argtypes, user32.GetAncestor.restype = [wt.HWND, wt.UINT], wt.HWND
user32.GetWindowLongPtrW.argtypes, user32.GetWindowLongPtrW.restype = [wt.HWND, ctypes.c_int], ctypes.c_ssize_t
k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
k32.QueryFullProcessImageNameW.restype = wt.BOOL
dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwm.DwmGetWindowAttribute.restype = ctypes.c_long                      # raw HRESULT, 0 = S_OK
```

## 3. Elevation and UIPI (`wb_windows_probe.py`)
Own process: TokenElevation=0; TokenElevationType=3 (Limited = admin user with a UAC split token); integrity medium
(0x2000); uiAccess=0. UAC policy: EnableLUA=1, ConsentPromptBehaviorAdmin=5. Survey of all 352 processes:
`WTSEnumerateProcessesW` (session and name without opening the process), then
`OpenProcess(LIMITED)` -> `OpenProcessToken(TOKEN_QUERY)` -> `GetTokenInformation`.

| Group | Count | Result |
|---|---|---|
| own session, medium / low / untrusted IL | 128 / 17 / 80 | readable (low and untrusted = browser sandboxes, UWP) |
| own session, **elevated** (taskhostw.exe) | 1 | **readable from medium IL**: elevated=1, IL high |
| own session, UIAccess (TabTip, ctfmon) | 2 | IL high, elevated=0, uiAccess=1 (matches [M8]) |
| own session: csrss, dwm, winlogon, fontdrvhost, a driver service | 5 | OpenProcess fails, **ERROR_ACCESS_DENIED (5)** |
| session 0 services | 115 / 2 / 1 | OpenProcess error 5 / OpenProcessToken error 5 / readable (IL system) |
| PID 0 | 1 | OpenProcess error 87 |

A same-user elevated target is therefore detectable (one sample). Error 5 means a system, other-user or protected
process, which may include anti-cheat-protected games: treat it as **unknown, probably elevated**. Compare integrity
levels, because that is the UIPI criterion: "Applications are permitted to inject input only into applications that
are at an equal or lesser integrity level", and "neither GetLastError nor the return value will indicate the failure
was caused by UIPI blocking" [M1]. uiAccess requires a signed app in a secure location such as Program Files and is
meant for assistive technology only [M8], so it is not an option. Keep AutoPress `asInvoker` (no `--uac-admin`).
What AutoPress should tell the user (when the target is picked, and before every run):
* Target IL above own IL: block the run. Suggested text: 「目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的
  模擬輸入。請按「以系統管理員身分重新啟動 AutoPress」。」 With TokenElevationType 3 a consent prompt is enough. With
  type 1 and not elevated (a standard user), say that an administrator account is required.
* Unknown (error 5): warn but allow: 「無法讀取目標程式的權限（可能是系統或受保護程式）；若輸入沒有反應，請以系統管理員
  身分執行 AutoPress。」 Because failures are silent, verify each step's effect (OCR or a pixel change; input is R2a's area).
```python
# verified (wb_win32.token_info): integrity RID from TOKEN_MANDATORY_LABEL; restypes: BOOL, P(c_ubyte), P(DWORD)
adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
adv.GetSidSubAuthorityCount.argtypes, adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p], [ctypes.c_void_p, wt.DWORD]
adv.GetTokenInformation(tok, 25, buf, len(buf), ctypes.byref(n))     # 25 TokenIntegrityLevel, 20 TokenElevation
sid = SID_AND_ATTRIBUTES.from_buffer(buf).Sid                         # struct {c_void_p Sid; DWORD Attributes}
rid = adv.GetSidSubAuthority(sid, adv.GetSidSubAuthorityCount(sid).contents.value - 1).contents.value
```

## 4. Screen capture (mss 10.2 GDI: BitBlt `SRCCOPY|CAPTUREBLT` into a DIB section, `gdi.py:380`)
**Pixel-exact check** (`wb_qt_probe.py --visible`). An own 400x150-logical window drew a per-pixel pattern through a
QImage that carries the window's dpr, and mss grabbed the window's physical client rect. Variants: default, 1.25, 1.5,
mixed, each on both screens (8 runs). Every run matched 100 % at offset (0,0); the best of the 80 shifted offsets
matched 0 %. The window was captured 16-35 ms after `show()`. Layered windows are included (CAPTUREBLT [M13]), and
negative coordinates work. mss `monitors[1:]` equal the EnumDisplayMonitors rects; their `name` is
"Generic PnP Monitor", so match them by rect.

| Timing (`wb_capture_timing.py` x3 + base run; medians) | ms |
|---|---|
| `mss.MSS()` + close | 0.1-0.2 |
| grab 400x150 region (either monitor) | 8.3-8.4 (min 5-7) |
| grab one 1920x1080 monitor / both monitors 3840x1080 | 17-22 / 33-36 |
| alternating two region sizes (the DIB is re-created at each change) | +1-4 per change (noisy) |
| `np.asarray(shot)`: zero-copy (h,w,4) BGRA view (`__array_interface__`, `owndata=False`) | 0.002 |
| `np.frombuffer(shot.bgra)` (bytes copy) / BGR copy `a[..., :3]` / RGB copy `a[..., 2::-1]` | 1.8-2.4 / 21-24 / 10.6-12 |
| `Image.frombuffer("RGB", size, shot.bgra, "raw", "BGRX", 0, 1)` | 6.6-7.7 |

`ScreenShot.raw` (removal in 11.0; use `bgra`) and `mss.mss()` are deprecated [S2].
**Threads:** two QThreads, each with its own `mss.MSS()`: 20/20 correct each. One MSS shared by 3 Python threads:
60/60 correct. mss 10.2 locks per instance and documents both patterns [S1][S2].
**QScreen.grabWindow(0, x, y, w, h):** x and y are logical and relative to **the screen's** top-left on Windows; the
pixmap is physical, with dpr set [Q2]. Measured 8/8 exact (for example 500x188 at dpr 1.25). Global logical
coordinates failed on the secondary screen (0 %). It also worked from a QThread with no warning, but Qt only promises
QPixmap in threads "for most platforms" [Q3].
**Caveats:** most exclusive-fullscreen DirectX/OpenGL apps cannot be captured by Desktop Duplication, and GDI capture
"is not perfect" [M13]. The python-mss report for a fullscreen game got the desktop instead of the game, with no fix
"without DLL injection" [S3]. Tell users to use **borderless/windowed** mode, and flag uniform or stale captures.
* PrintWindow(hwnd, hdc, PW_CLIENTONLY) captures occluded windows. The target renders the image via WM_PRINT and the
  call is synchronous [M9], so it can hang; GPU-rendered content may come out black. `PW_RENDERFULLCONTENT` (0x2) is
  not on that page. Both points are unverified.
* Windows.Graphics.Capture: `CreateForWindow(HWND)` needs Windows 10 1903+ [M11]. It captures GPU and occluded windows,
  but on Windows 10 a yellow border is always drawn [M10] (`IsBorderRequired` needs build 20348+ plus consent [M12]).
  It needs WinRT/D3D11 interop, so treat it as a later option only.

## 5. Region / point picker for mixed-DPI multi-monitor
On "pick", grab every monitor with mss. Then show **one frameless, always-on-top Tool overlay per QScreen**
(`setGeometry(screen.geometry())`) that paints its monitor's shot as a Format_RGB32 QImage with
`setDevicePixelRatio(screen.devicePixelRatio())` at (0,0). That is 1:1 in physical pixels; the pattern test above
verified this path at 1.25 and 1.5. Mouse to physical: `phys = monitor_origin + qRound(event.position()*dpr)` (QPointF,
monitor matched by origin), or `GetCursorPos()`. A rubber band converts both corners. To outline a known physical rect,
such as the target's client area: `local = (phys - origin) / dpr`. Never go through global logical coordinates
(islands and gaps). Take keyboard focus only while picking; ESC cancels; hide the overlays before `WindowFromPoint`.
Verified with hidden windows only (`wb_qt_probe.py` "overlay"; nothing covered the desktop):
* overlay HWND rect = monitor rect in 22/22 run×screen cases, including 1.75 (logical 1097x617 -> 1920x1080);
* native children at local rects (0,0,1,1), (7,9,13,11), (333,211,401,151) and at the bottom-right corner landed on
  `origin + qRound(local*dpr)` with size `qRound(size*dpr)`: 56/56 under scaled variants, 32/32 at dpr 1.

## 6. Coordinate storage for profiles (`wb_coords.py`)
Store every point and region relative to the target's **client area**, in physical pixels, with the reference client
size and DPI:
`ClientPoint(dx, dy, rx=(dx+0.5)/ref_w, ry=(dy+0.5)/ref_h, ref_w, ref_h, anchor, ref_dpi)` and
`ClientRegion(dx, dy, w, h, rx, ry, rw, rh, ref_w, ref_h, ref_dpi)`.
Resolving modes: `offset` (exact pixels; anchor tl/tr/bl/br/center), `ratio` (`floor(rx*cw)`, clamped), and `auto`
(offset if the client size is unchanged, otherwise ratio).
* Same size: use offset. Round trips are exact in every mode and anchor (36,502 checks, including negative origins).
* Resized with uniform scaling (game UIs that scale with resolution; DPI-unaware targets stretched by Windows): use
  ratio. 1280x720 -> 1920x1080 resolved to the pixel containing the scaled centre in 500/500 cases. Live check with two
  hidden windows, 800x600 -> 1000x750: point (125,63) and region (250,125,375,100), as predicted.
* UI pinned to an edge (for example a bottom-right "OK" button): offset with that anchor. Reflowing web pages: locate
  by OCR text, and keep the coordinates as a fallback.
* If ref_dpi or the client size differs from now, re-validate once by OCR or a preview before a batch run.
  Pitfall (measured): `setGeometry()` on a `WA_DontShowOnScreen` widget does not reach the HWND until it is shown.

## 7. Recommended module API
```python
# autopress/platform/dpi.py  (import after QApplication)        Rect = tuple[int, int, int, int]  # x, y, w, h physical
@dataclass(frozen=True)
class Monitor: device: str; rect: Rect; work: Rect; dpi: int; primary: bool
def ensure_per_monitor_v2() -> str                    # report awareness; SetProcessDpiAwarenessContext(-4) if no Qt
def monitors() -> list[Monitor]
def monitor_for_screen(screen: QScreen) -> Monitor    # by native origin
def screen_to_physical(screen: QScreen, p: QPointF) -> tuple[int, int]   # origin + qRound((p - origin) * dpr)
def physical_to_screen(screen: QScreen, x: int, y: int) -> QPointF
def widget_to_physical(w: QWidget, local: QPointF) -> tuple[int, int]   # ClientToScreen(top) + qRound(mapTo*dpr)
def cursor_physical() -> tuple[int, int]              # GetCursorPos
# autopress/platform/windows.py
@dataclass(frozen=True)
class WindowKey: exe: str; cls: str; title_re: str | None
def list_windows(alt_tab_only: bool = True) -> list[WindowInfo]   # hwnd, title, cls, pid, exe, iconic, rect
def window_at(x: int, y: int) -> int | None           # WindowFromPoint + GA_ROOT (own overlays hidden first)
def client_rect(hwnd: int) -> Rect; def window_rect(hwnd: int) -> Rect; def frame_bounds(hwnd: int) -> Rect | None
def is_alive(hwnd: int, key: WindowKey, pid: int) -> bool; def find_window(key: WindowKey) -> int | None
def is_minimized(hwnd: int) -> bool; def restored_rect(hwnd: int) -> Rect   # GetWindowPlacement, workspace coords
def token_info(pid: int | None = None) -> TokenInfo    # il_rid | None, elevated, elevation_type, uiaccess, error
def input_permission(hwnd: int) -> Literal["ok", "blocked_elevated", "unknown"]
# autopress/platform/capture.py
class Grabber:                                        # one per thread; construction costs 0.1-0.2 ms
    def grab(self, rect: Rect) -> np.ndarray          # (h, w, 4) BGRA via np.asarray(shot); copy before mutating
    def grab_monitor(self, m: Monitor) -> np.ndarray
    def grab_client(self, hwnd: int, region: ClientRegion | None = None) -> np.ndarray
    def close(self) -> None
def bgr(a: np.ndarray) -> np.ndarray; def to_qimage(a: np.ndarray, dpr: float) -> QImage   # RGB32 + setDevicePixelRatio
def looks_blank(a: np.ndarray) -> bool                # uniform frame -> exclusive-fullscreen warning
```

## 8. Pitfalls (measured unless cited)
1. `mss.MSS()` before `QApplication` locks the process into PMv1, and Qt's PMv2 call fails. Compare DPI contexts with
   `AreDpiAwarenessContextsEqual`: GetThreadDpiAwarenessContext() returned 0x22, not -4 (`wb_capture_timing.py`).
2. Logical global space has gaps under mixed DPI. The global formula can be off by 1 px for widgets, and
   `QCursor.pos()` by up to dpr/2. `QScreen.grabWindow(0, ...)` takes screen-relative logical coordinates.
3. WindowFromPoint skips input-transparent layered windows and hidden windows. Iconic windows report -32000 rects.
   `rcNormalPosition` is in workspace coordinates. GetWindowRect includes invisible borders, so use the client rect.
4. `IsWindow` alone is unsafe because handles are recycled [M4]. UIPI failures are silent [M1]. A dev run's exe is the
   base python.exe.
5. `ScreenShot.raw` and `mss.mss()` are deprecated [S2]. `bgra` costs a 2 ms copy at 1080p; `np.asarray(shot)` is free.
6. Keep references to ctypes callbacks, pass POINT by value, and declare argtypes and restype everywhere (64-bit handles).

## Open issues
* Windows-level 125/150 % and mixed DPI, virtualization of DPI-unaware targets, and WM_DPICHANGED when AutoPress moves
  between monitors were not measurable (both monitors are at 100 %). Re-run `wb_run_suite.py`, `wb_windows_probe.py`
  and `wb_capture_timing.py` on a 150 % machine.
* Only one same-user elevated process was available (taskhostw.exe); a UAC-elevated game was not tested. The
  `ShellExecuteW("runas")` restart was not tested (it would show a UAC prompt).
* Exclusive-fullscreen capture, PrintWindow and WGC come from sources only: no fullscreen game was available.

## Sources
[M1] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
[M2] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext
[M3] https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows
[M4] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindow  [M5] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-windowfrompoint
[M6] https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-windowplacement  [M7] https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
[M8] https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview  [M9] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow
[M10] https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture
[M11] https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow
[M12] https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession.isborderrequired
[M13] https://learn.microsoft.com/en-us/archive/blogs/dsui_team/ways-to-capture-the-screen (Microsoft, 2013)
[Q1] https://doc.qt.io/qt-6/highdpi.html  [Q2] https://doc.qt.io/qt-6/qscreen.html  [Q3] https://doc.qt.io/qt-6/threads-modules.html
[S1] https://python-mss.readthedocs.io/latest/usage.html  [S2] https://python-mss.readthedocs.io/latest/release-history/v10.2.0.html
[S3] https://github.com/BoboTiG/python-mss/issues/28
Local mss source: `.venv/Lib/site-packages/mss/windows/gdi.py:247-259,380`, `mss/base.py:255,311`, `mss/factory.py:17`, `mss/screenshot.py:45,87`.
