# OWNED BY G3
"""win32.windows / dpi / elevation / power without showing anything: own HIDDEN native windows
(ctypes, real HWNDs on the offscreen platform), patched enumerations, pure DPI math (SPEC 8.2)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF

from autopress.models import Monitor, TargetMatch, TitleMatch, WindowInfo
from autopress.win32 import api, dpi, elevation, power, windows
from tests.win32_helpers import WS_EX_TOOLWINDOW, FakeScreen, hidden_window

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------- own hidden window


def test_client_rect_and_window_info_of_an_own_hidden_window() -> None:
    with hidden_window("AutoPress G3 hidden 測試", rect=(240, 160, 420, 300)) as hwnd:
        wr = windows.window_rect(hwnd)
        assert wr == (240, 160, 420, 300)
        cx, cy, cw, ch = windows.client_rect(hwnd)
        assert 240 < cx < 240 + 30 and 160 < cy < 160 + 60  # inside the frame (borders + caption)
        assert 0 < cw < 420 and 0 < ch < 300
        info = windows.window_info(hwnd)
        assert info is not None
        assert info.hwnd == hwnd and info.title == "AutoPress G3 hidden 測試" and info.class_name == "Static"
        assert info.pid == os.getpid() and info.exe_path.lower().endswith("python.exe")
        assert info.rect == wr and info.client == (cx, cy, cw, ch)
        assert info.visible is False and info.minimized is False
        assert windows.restored_rect(hwnd)[2:] == wr[2:]  # normal position, workspace coordinates
        assert windows.is_window(hwnd) and windows.is_own_window(hwnd) and not windows.is_minimized(hwnd)
        assert windows.window_pid(hwnd) == os.getpid()
        assert windows.is_alive(info)
        assert windows.window_dpi(hwnd) in (96, 120, 144, 168, 192)
        fb = windows.frame_bounds(hwnd)
        assert fb is None or len(fb) == 4
        assert windows.is_alive(WindowInfo(hwnd=hwnd, pid=info.pid, class_name="OtherClass")) is False
        assert windows.is_alive(WindowInfo(hwnd=hwnd, pid=info.pid + 1, class_name="Static")) is False
        assert windows.is_alive(WindowInfo(hwnd=hwnd, pid=info.pid, class_name="Static",
                                           exe_path="C:/elsewhere/other.exe")) is False
    assert windows.window_info(hwnd) is None
    assert windows.is_alive(info) is False and windows.is_window(hwnd) is False
    for fn in (windows.client_rect, windows.window_rect, windows.restored_rect):
        with pytest.raises(OSError):
            fn(hwnd)
    assert windows.window_dpi(0) == 96 and windows.foreground_window() >= 0


def test_list_windows_never_shows_own_windows() -> None:
    with hidden_window("AutoPress G3 never listed") as hwnd:
        listed = windows.list_windows(alt_tab_only=False)
        assert all(w.pid != os.getpid() for w in listed)
        assert all(w.title and w.visible for w in listed)
        assert hwnd not in [w.hwnd for w in listed]


def test_exclude_from_capture_on_an_own_window() -> None:
    """Sets / clears the display affinity (the mss effect itself is measured in realinput)."""
    with hidden_window("AutoPress G3 affinity") as hwnd:
        ok = windows.exclude_from_capture(hwnd, True)
        if ok:
            assert windows.display_affinity(hwnd) == api.WDA_EXCLUDEFROMCAPTURE
            assert windows.exclude_from_capture(hwnd, False) is True
            assert windows.display_affinity(hwnd) == api.WDA_NONE
        else:  # some builds refuse it for never-shown windows: must still not raise
            assert windows.display_affinity(hwnd) in (None, api.WDA_NONE)
    assert windows.exclude_from_capture(0) is False


# ----------------------------------------------------------------------------- find_windows


def _fake(hwnd: int, exe: str, title: str, cls: str = "Main") -> WindowInfo:
    return WindowInfo(hwnd=hwnd, title=title, class_name=cls, pid=hwnd + 1, exe_path=f"C:\\Games\\{exe}")


FAKES = [_fake(10, "chrome.exe", "Gmail - Google Chrome", "Chrome_WidgetWin_1"),
         _fake(20, "chrome.exe", "兌換中心 - Google Chrome", "Chrome_WidgetWin_1"),
         _fake(30, "Game.EXE", "My Game", "UnityWndClass"),
         _fake(40, "game.exe", "My Game launcher", "Qt6QWindowIcon"),
         _fake(50, "chrome.exe", "兌換 popup", "Chrome_WidgetWin_2")]


def test_find_windows_filters_with_targetmatch_and_keeps_z_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "list_windows", lambda alt_tab_only=True: list(FAKES))
    tool = {50}
    monkeypatch.setattr(api, "exstyle", lambda h: WS_EX_TOOLWINDOW if h in tool else 0)
    found = windows.find_windows(TargetMatch(exe="chrome.exe", title="兌換", title_mode=TitleMatch.CONTAINS))
    assert [w.hwnd for w in found] == [20, 50]  # alt-tab window first, tool window last
    assert [w.hwnd for w in windows.find_windows(TargetMatch(exe="GAME.exe"))] == [30, 40]
    assert [w.hwnd for w in windows.find_windows(TargetMatch(exe="game.exe", class_name="UnityWndClass"))] == [30]
    assert [w.hwnd for w in windows.find_windows(TargetMatch(title="My Game", title_mode=TitleMatch.EXACT))] == [30]
    assert [w.hwnd for w in windows.find_windows(TargetMatch(title=r"^my game$", title_mode=TitleMatch.REGEX))] == [30]
    assert windows.find_window(TargetMatch(exe="chrome.exe")).hwnd == 10
    assert windows.find_window(TargetMatch(exe="nothing.exe")) is None
    tool.add(10)
    assert windows.find_window(TargetMatch(exe="chrome.exe")).hwnd == 20


def test_find_windows_never_returns_own_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    with hidden_window("AutoPress G3 own") as hwnd:
        own = WindowInfo(hwnd=hwnd, title="AutoPress", class_name="Static", pid=os.getpid(),
                         exe_path="C:\\Python312\\python.exe")
        monkeypatch.setattr(windows, "list_windows", lambda alt_tab_only=True: [own])
        assert windows.find_windows(TargetMatch(exe="python.exe")) == []


# ----------------------------------------------------------------------------- window_at


def test_window_at_returns_a_root_or_none() -> None:
    vx, vy, vw, vh = dpi.virtual_screen()
    for x, y, skip in ((vx + vw // 2, vy + vh // 2, False), (vx + vw // 2, vy + vh // 2, True),
                       (vx - 50000, vy - 50000, False)):
        hit = windows.window_at(x, y, skip_own=skip)
        assert hit is None or (isinstance(hit, int) and hit > 0)
        if skip and hit:
            assert not windows.is_own_window(hit)


class Desk:
    """Patched z-order: (hwnd, pid, rect, exstyle, visible, iconic) topmost first."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, wins: list[tuple], hit: int) -> None:
        self.wins = {w[0]: w for w in wins}
        order = [w[0] for w in wins]
        monkeypatch.setattr(api, "WindowFromPoint", lambda pt: hit)
        monkeypatch.setattr(api, "GetAncestor", lambda h, flag: h)
        monkeypatch.setattr(api, "enum_windows", lambda: list(order))
        monkeypatch.setattr(api, "window_pid", lambda h: self.wins[h][1] if h in self.wins else 0)
        monkeypatch.setattr(api, "exstyle", lambda h: self.wins[h][3])
        monkeypatch.setattr(api, "IsWindowVisible", lambda h: self.wins[h][4])
        monkeypatch.setattr(api, "IsIconic", lambda h: self.wins[h][5])
        monkeypatch.setattr(api, "is_cloaked", lambda h: False)
        monkeypatch.setattr(windows, "window_rect", lambda h: self.wins[h][2])


def test_window_at_skip_own_looks_through_autopress_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    me = os.getpid()
    full = (0, 0, 1920, 1080)
    wins = [
        (1, me, full, 0, True, False),  # AutoPress main window on top of everything
        (2, 900, (50, 50, 10, 10), 0, True, False),  # small foreign window elsewhere
        (3, 901, full, api.WS_EX_TRANSPARENT | api.WS_EX_LAYERED, True, False),  # click-through overlay
        (4, 902, full, 0, False, False),  # hidden
        (5, 903, full, 0, True, True),  # minimized
        (6, me, full, api.WS_EX_TOOLWINDOW, True, False),  # AutoPress mini bar
        (7, 904, (100, 100, 800, 600), 0, True, False),  # the target
        (8, 905, full, 0, True, False),  # desktop-sized window below
    ]
    Desk(monkeypatch, wins, hit=1)
    assert windows.window_at(300, 300) == 1  # plain WindowFromPoint semantics
    assert windows.window_at(300, 300, skip_own=True) == 7
    assert windows.window_at(55, 55, skip_own=True) == 2
    assert windows.window_at(1500, 900, skip_own=True) == 8
    Desk(monkeypatch, wins, hit=7)  # nothing of ours on top: WindowFromPoint's answer is exact
    assert windows.window_at(300, 300, skip_own=True) == 7
    Desk(monkeypatch, [(1, me, full, 0, True, False)], hit=1)
    assert windows.window_at(300, 300, skip_own=True) is None
    Desk(monkeypatch, [], hit=0)
    assert windows.window_at(300, 300) is None


# ----------------------------------------------------------------------------- dpi


def test_qround_matches_qt6() -> None:
    for v in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 0.49, -0.49, 7.0):
        assert dpi.qround(v) == QPointF(v, v).toPoint().x(), v


SECONDARY = FakeScreen(-1920, 0, 1536, 864, 1.25)  # native origin kept, logical size = 1920x1080 / 1.25
PRIMARY = FakeScreen(0, 0, 1280, 720, 1.5)


def test_screen_to_physical_keeps_the_native_origin() -> None:
    """Measured cases of win32_windows.md 1 (mixed 1.25 / 1.5)."""
    assert dpi.screen_to_physical(SECONDARY, QPointF(-1819, 67)) == (-1794, 84)
    assert dpi.screen_to_physical(PRIMARY, QPointF(101, 67)) == (152, 101)
    assert dpi.screen_to_physical(FakeScreen(-1920, 0, 1280, 720, 1.5), QPointF(-1819, 67)) == (-1768, 101)
    assert dpi.screen_to_physical(FakeScreen(-1920, 0, 1097, 617, 1.75), QPointF(-1819, 67)) == (-1743, 117)
    assert dpi.screen_to_physical(FakeScreen(0, 0, 1920, 1080, 1.0), QPointF(5, 6)) == (5, 6)


def test_physical_to_screen_is_the_inverse() -> None:
    for screen in (SECONDARY, PRIMARY):
        o = screen.geometry().topLeft()
        for phys in ((o.x(), o.y()), (o.x() + 1000, o.y() + 500), (o.x() + 1919, o.y() + 1079)):
            logical = dpi.physical_to_screen(screen, *phys)
            assert dpi.screen_to_physical(screen, logical) == phys


def test_local_to_physical_for_overlays() -> None:
    assert dpi.local_to_physical(SECONDARY, QPointF(0, 0)) == (-1920, 0)
    assert dpi.local_to_physical(SECONDARY, QPointF(101, 67)) == (-1920 + 126, 84)
    assert dpi.local_to_physical(PRIMARY, QPointF(1279.5, 719.5)) == (1919, 1079)


def test_monitor_for_screen_matches_by_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    mons = [Monitor("\\\\.\\DISPLAY1", (0, 0, 1920, 1080), (0, 0, 1920, 1040), 144, True),
            Monitor("\\\\.\\DISPLAY2", (-1920, 0, 1920, 1080), (-1920, 0, 1920, 1040), 120, False)]
    monkeypatch.setattr(dpi, "monitors", lambda: mons)
    assert dpi.monitor_for_screen(SECONDARY) is mons[1]
    assert dpi.monitor_for_screen(PRIMARY) is mons[0]
    assert dpi.monitor_for_screen(FakeScreen(5000, 0, 100, 100, 1.0)) is None


def test_real_monitors_and_helpers(qapp: object) -> None:
    mons = dpi.monitors()
    assert mons and mons[0].primary
    assert sum(m.primary for m in mons) == 1
    vx, vy, vw, vh = dpi.virtual_screen()
    for m in mons:
        x, y, w, h = m.rect
        assert vx <= x and vy <= y and x + w <= vx + vw and y + h <= vy + vh and m.dpi >= 96
        assert dpi.monitor_at(x + w // 2, y + h // 2) == m
    assert dpi.primary_monitor() == mons[0]
    assert dpi.monitor_at(vx - 100000, vy) in mons  # nearest monitor when outside all
    assert dpi.process_awareness() in ("unaware", "system", "pmv1", "pmv2")
    pos = dpi.cursor_physical()
    assert isinstance(pos, tuple) and len(pos) == 2


def test_widget_to_physical_falls_back_without_a_native_window(qapp: object) -> None:
    from PyQt6.QtWidgets import QWidget

    w = QWidget()
    w.setGeometry(100, 80, 300, 200)
    child = QWidget(w)
    child.setGeometry(10, 20, 50, 50)
    w.show()  # offscreen platform: winId() is not a real HWND -> Qt's own mapping
    try:
        x, y = dpi.widget_to_physical(child, QPointF(5, 5))
        gx = child.mapToGlobal(QPointF(5, 5))
        assert (x, y) == (round(gx.x()), round(gx.y()))
    finally:
        w.close()


def test_ensure_per_monitor_v2_in_a_qt_less_process(clean_env: dict[str, str]) -> None:
    code = ("from autopress.win32 import dpi\n"
            "before = dpi.process_awareness()\n"
            "print(before, dpi.ensure_per_monitor_v2(), dpi.ensure_per_monitor_v2())\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=clean_env, capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    before, first, second = out.stdout.split()
    assert before == "unaware" and first == second == "pmv2"


# ----------------------------------------------------------------------------- elevation


def test_token_of_own_process() -> None:
    info = elevation.token_info()
    assert info.pid == os.getpid() and info.error == 0
    assert info.integrity_rid in (0x2000, 0x2100, 0x3000, 0x4000)
    assert info.elevated in (True, False) and info.elevation_type in (1, 2, 3)
    assert info.uiaccess is False
    assert elevation.is_elevated() == (bool(info.elevated) or info.integrity_rid >= 0x3000)
    assert elevation.can_elevate() == (info.elevation_type == 3)
    assert elevation.token_info(os.getpid()).integrity_rid == info.integrity_rid


def test_unreadable_tokens_are_reported_not_raised() -> None:
    assert elevation.token_info(0).error != 0 and elevation.token_info(0).integrity_rid is None
    assert elevation.token_info(4).integrity_rid is None or elevation.token_info(4).integrity_rid >= 0x4000  # System


def test_input_permission() -> None:
    with hidden_window("AutoPress G3 permission") as hwnd:
        assert elevation.input_permission(hwnd) is elevation.InputPermission.OK
    assert elevation.input_permission(0) is elevation.InputPermission.UNKNOWN
    assert elevation.input_permission(hwnd) is elevation.InputPermission.UNKNOWN  # destroyed


def test_input_permission_compares_integrity_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    levels = {os.getpid(): 0x2000, 111: 0x3000, 222: 0x2000, 333: 0x1000, 444: None}
    monkeypatch.setattr(api, "window_pid", lambda h: int(h))
    monkeypatch.setattr(elevation, "token_info", lambda pid=None: elevation.TokenInfo(
        pid=pid or os.getpid(), integrity_rid=levels[pid or os.getpid()], error=0 if levels[pid or os.getpid()] else 5))
    P = elevation.InputPermission
    assert [elevation.input_permission(h) for h in (111, 222, 333, 444)] == [P.BLOCKED_ELEVATED, P.OK, P.OK, P.UNKNOWN]


def test_restart_command_adds_wait_lock_once(monkeypatch: pytest.MonkeyPatch) -> None:
    exe, params, cwd = elevation.restart_command(["--lang", "zh TW"])
    assert exe == sys.executable and Path(cwd) == ROOT
    assert params.endswith('--lang "zh TW" --wait-lock') and "main.py" in params
    _exe, params2, _cwd = elevation.restart_command(["--wait-lock"])
    assert params2.count("--wait-lock") == 1
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe3, params3, cwd3 = elevation.restart_command([])
    assert exe3 == sys.executable and params3 == "--wait-lock" and Path(cwd3) == Path(sys.executable).resolve().parent


def test_restart_as_admin_uses_runas(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def fake_shell(hwnd: object, verb: str, exe: str, params: str, cwd: str, show: int) -> int:
        calls.append((verb, exe, params, cwd, show))
        return result[0]

    result = [42]
    monkeypatch.setattr(api, "ShellExecuteW", fake_shell)  # never shows a UAC prompt in tests
    assert elevation.restart_as_admin(["--x"]) is True
    assert calls[0][0] == "runas" and calls[0][2].endswith("--x --wait-lock")
    result[0] = 5  # SE_ERR_ACCESSDENIED: the user declined the prompt
    assert elevation.restart_as_admin([]) is False


# ----------------------------------------------------------------------------- power


def test_keep_awake_in_a_worker_thread() -> None:
    results: list[bool] = []

    def run() -> None:  # per-thread state: the thread exits right after, clearing it anyway
        results.append(power.keep_awake(True))
        results.append(power.keep_awake(False))

    t = threading.Thread(target=run)
    t.start()
    t.join(5)
    assert results == [True, True]


def test_keep_awake_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(api, "SetThreadExecutionState", lambda flags: seen.append(flags) or 0x80000000)
    assert power.keep_awake(True) and power.keep_awake(False)
    assert seen == [0x80000003, 0x80000000]
    monkeypatch.setattr(api, "SetThreadExecutionState", lambda flags: 0)
    assert power.keep_awake(True) is False
