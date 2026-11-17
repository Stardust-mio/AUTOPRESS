# SPEC v1 - adversarial technical critique

Reviewer: fresh-context reviewer, TECHNICAL lens (Win32 / DPI / threading / Qt lifecycle / OCR API /
interfaces / tests / packaging). Date: 2026-11-17. Read-only review: nothing in the project was changed
except this file.

## Summary

**Counts: 0 blocker, 15 major, 26 minor (41 items).**

Most important:
1. T01 (major) - the mini bar sits on top of a maximized target, is captured by OCR (its result chips
   say 已使用 / 無效 / 已過期 = default keywords) and blocks clicks; the SPEC only places it "away from the target".
2. T05 (major) - default keywords + class order classify "cannot be redeemed" as SUCCESS and success
   messages that mention expiry as EXPIRED (verified with the documented rule).
3. T02 (major) - run mode hides the main window, so closing any parentless dialog quits the app in the
   middle of a run (verified: lastWindowClosed + aboutToQuit).

No item was rated blocker: every defect below has a workaround a careful group could find, but several
(T01, T02, T03, T08, T09, T10, T11) are cross-group gaps where groups will otherwise guess differently.

## Method and evidence

* Read all of SPEC.md, docs/research/{ocr,win32_input,win32_windows,ux}.md, docs/requirements.md,
  docs/design-preview/README.md, every stub under autopress/, the A1 foundation modules, tests/ and tools/.
* `.venv/Scripts/python.exe -m pytest -q`: 250 passed in 1.1 s.
* `tools/check_ownership.py`: 0 problems at first; 1 problem once review files existed (see T25).
* Probes (all in a session scratch folder outside the repo):
  * P1 `crit_roundtrip.py` -> `crit_roundtrip.json`: model round trips with unknown / missing / wrong keys.
  * P2 `crit_storage.py` -> `probe2/crit_storage.json`: storage side effects, `paths.is_writable_dir` race.
  * P3 `crit_classify.py` -> `crit_classify.json`: the rule of `runner/classify.py` on `models.DEFAULT_KEYWORDS`.
  * P4 `crit_qt.py` -> `crit_qt.json` (offscreen platform): `winId()` and last-window-closed in run mode.
  * P5 `crit_ocr_maxside.py`, `crit_ocr_ctrl*.py` -> `crit_ocr_*.json`: rapidocr 3.10 preprocessing and det_side.
  * P6 inline: `storage.write_text_atomic` into a scratch folder with `icacls /deny <me>:(WD)`, 15 s timeout
    (ACL removed and folder deleted afterwards).
  * P7 inline: monitor layout via EnumDisplayMonitors (read-only).

## Findings

### T01 [major] Mini bar over the target is captured by OCR and blocks clicks
- Where: SPEC 6.4 Overlays (SPEC.md:902-904 "placed away from the target"), SPEC 4.3 G7
  `MiniBar.place_away_from(rect)` (SPEC.md:689), `autopress/ui/minibar.py:5-7`, SPEC 5.3 `ocr_check`
  region None = whole client (SPEC.md:749); `docs/design-preview/README.md:62` promised the bar "會避開要點擊的位置和辨識區域".
- Problem: the bar is topmost, takes mouse clicks and is put "on the corner farthest from the target's client
  rect (or on another monitor)". With one monitor and a maximized or borderless-fullscreen target (Help even
  recommends borderless) every corner is inside the client area. (a) mss captures screen pixels (BitBlt +
  CAPTUREBLT), so the bar's text lands in every capture that overlaps it; its result chips use
  `CodeStatus.label()` ("已使用", "無效", "已過期"), which are default keywords. A whole-client `ocr_check`
  (allowed, only a WARNING) therefore matches USED (2nd in the class order) for every code after the first
  USED result - a silent cascade of wrong statuses written to history. (b) A click point under the bar fails
  the WindowFromPoint root check -> PointNotOnTarget -> hard pause. `place_away_from` only receives the
  target rect, not the click points / OCR regions the user was promised.
- Evidence: the mock-up the stub points to draws the chips "成功 5" and "已使用 1" plus the label "正在兌換"
  (`docs/research/scripts/ux/prototype.py:1176,1184`); USED keywords contain "已使用"
  (`autopress/models.py:1097`) = `CodeStatus.USED.label()` (`models.py:131`); whole-client ocr_check is only a
  warning (`models.py:1063-1065`); `wait_text` defaults to CONTAINS (`models.py:897`), so a whole-client wait
  for "兌換" is satisfied by the bar's own "正在兌換"; capture semantics in win32_windows.md section 4.
- Fix: (1) exclude AutoPress's own floating windows from capture: `SetWindowDisplayAffinity(hwnd,
  WDA_EXCLUDEFROMCAPTURE=0x11)` exists from Windows 10 2004 (build 19041; this PC is 19044) - UNVERIFIED with
  mss, G2/G7 must test - or hide the bar for the duration of each grab; (2) change the API to
  `place_away_from(rects: Sequence[Rect])` with every resolved click point and OCR region, and define the
  fallback when nothing is free (other monitor, collapsed 1-line bar); (3) make an unbounded whole-client
  `ocr_check` at least a preflight warning that names the mini bar risk.

### T02 [major] Closing a parentless dialog in run mode quits the application
- Where: SPEC 2.4 step 5 (SPEC.md:114, main window hidden), SPEC 2.8 (no quit policy), SPEC 4.3 G5
  `confirm(parent: QWidget | None, ...)` / `message(parent | None, ...)` (SPEC.md:594-595), MiniBar = Qt.Tool.
- Problem: while the main window is hidden the only visible window is the Tool mini bar (Qt clears
  WA_QuitOnClose for parentless Tool windows). Qt's quitOnLastWindowClosed then treats any parentless dialog
  that is closed as the last primary window and quits; `aboutToQuit` -> `session.shutdown()` aborts the run.
  Nothing in the SPEC sets `setQuitOnLastWindowClosed(False)` or forbids parentless dialogs during a run
  (stop confirmation from the bar, attention dialog, error boxes, excepthook UI, a file dialog).
- Evidence: P4 (offscreen): main window shown then hidden, Tool bar shown, parentless QDialog shown and
  closed -> events `["lastWindowClosed", "aboutToQuit"]`; the "still running" marker never ran.
- Fix: G5 `create_application`: `app.setQuitOnLastWindowClosed(False)` and quit explicitly from
  `MainWindow.closeEvent` (or toggle it in `set_run_mode`); require dialogs shown in run mode to have the
  mini bar or main window as parent.

### T03 [major] `paths.data_dir()` re-probes on every call and races between threads
- Where: `autopress/paths.py:114-124` (`is_writable_dir`, fixed probe name `.write-test-<pid>`),
  `paths.py:142-159` (`data_dir` falls back to `%TEMP%/AutoPress`, or to `%APPDATA%` in portable mode, when a
  probe fails); SPEC 5.1 (SPEC.md:712, evidence written by the runner backend), SPEC 6.3 (SPEC.md:849-850,
  status bar `target` refreshed every 2 s), `storage.ProfileStore.directory` (`storage.py:127-131`).
- Problem: every `settings_path()/profiles_dir()/evidence_dir()/...` call writes and deletes the same probe
  file. The runner thread calls it when saving evidence while the GUI thread calls it continuously
  (ProfileStore re-resolves the folder on every get/list/save; the 2 s status-bar refresh goes through
  `ctx.active_profile()`; G1 may resolve queue/history paths per save). A collision makes one caller get
  False and silently use another data folder: evidence links point to the wrong root, the active profile
  "disappears", or the queue is saved where the next start will not look. Also: one disk write per 2 s for
  the whole app lifetime.
- Evidence: P2 - two threads x 3000 calls of `paths.is_writable_dir(<one folder>)` -> 2677 False results;
  single-thread control 0/3000.
- Fix: resolve the data folder once at startup and cache it (e.g. `paths.resolve_data_dir() ->
  (path, fallback_reason)` called by ui.app, later calls return the cached path); unique probe names
  (uuid4); never probe again after startup.

### T04 [major] Failsafe corner cannot be hit on multi-monitor layouts such as this PC
- Where: SPEC 2.6 (SPEC.md:153 "PRIMARY monitor's (0, 0)"), `autopress/win32/input.py:145-147`, SPEC 7.1
  failsafe text, design preview line 123 ("滑鼠移到螢幕左上角立刻停止").
- Problem: on this PC the second monitor is LEFT of the primary. (0, 0) is a point on the shared top edge,
  not a corner: pushing the mouse into the top-left corner ends at (-1920, 0) and never triggers, while
  moving along the top edge between the monitors can trigger it by accident. The research PC is the user's
  PC, so the documented emergency gesture does not work for the user.
- Evidence: P7 - monitors `[(0,0,1920,1080,primary), (-1920,0,1920,1080)]`, virtual screen
  `(-1920, 0, 3840, 1080)`; same layout in win32_input.md:3-4.
- Fix: trigger within `margin_px` of the top-left corner of ANY monitor (or of the virtual screen when a
  monitor covers it), say so in Help, and add a pure test with this two-monitor layout.

### T05 [major] Default keywords give false SUCCESS / EXPIRED results
- Where: `autopress/models.py:1115-1120` (SUCCESS has bare "redeemed", "claimed"), `models.py:1101-1103`
  (EXPIRED has bare "過期" and "expired" with fuzzy matching), SPEC 5.5 (SPEC.md:768-774),
  `runner/classify.py` docstring.
- Problem: SUCCESS is tested last and contains words that also occur in failure messages; EXPIRED is tested
  before SUCCESS and matches success messages that mention an expiry date. Wrong final statuses are written
  to history; a false SUCCESS is also skipped on every later import. SPEC 5.5 only claims correctness on the
  26 bench strings.
- Evidence: P3 with the documented rule (squash, class order, fuzzy_contains):
  "This code cannot be redeemed in your region." -> success; "The code could not be redeemed. Please check
  the code." -> success; "Redeemed successfully! Rewards expire in 7 days." -> expired (fuzzy);
  "兌換成功！獎勵已發送至信箱，請於過期前領取" -> expired; "兌換成功，道具將於 7 天後過期" -> expired;
  "Account not bound to a character" -> invalid (fuzzy "not found").
- Fix: remove bare "redeemed" / "claimed" / "過期" (keep "redeemed successfully", "successfully redeemed",
  "已過期", "has expired"); add a negation rule ("cannot", "could not", "unable", "failed", "無法", "失敗"
  next to a SUCCESS keyword -> UNKNOWN); no fuzzy for "expired"; add these sentences to the U3 list in
  `tests/test_models.py`.

### T06 [major] Importing a malformed profile renames the user's own file
- Where: `autopress/storage.py:82-101` (`read_json` renames invalid JSON to `*.broken-<ts>`),
  `storage.py:188-199` (`ProfileStore.import_file` calls it on a user-chosen path), `storage.py:209-223`
  (templates in the install folder); SPEC 6.4.2 (SPEC.md:879-880), SPEC 7.1 "profile import invalid".
- Problem: the quarantine meant for data-folder files is applied to arbitrary files: picking a damaged or
  wrong `.json` in the import dialog renames the user's file in Downloads/Desktop; it no longer ends with
  `.autopress.json`, so the user cannot find or double-click it.
- Evidence: P2 - importing a malformed `朋友的設定檔.autopress.json` raised the localized StorageError and
  the file became `朋友的設定檔.autopress.json.broken-20261117-162917`.
- Fix: `read_json(path, default, quarantine=False)` for foreign files (import, templates); only settings,
  queue and history are quarantined.

### T07 [major] Atomic writes hang the GUI in write-denied folders
- Where: `autopress/storage.py:57-74` (`tempfile.mkstemp` in the destination folder), used by
  `ProfileStore.export_file`; the same pattern is prescribed for `imageio.save_png`
  (`autopress/ocr/imageio.py:50-52`) and `codes/csvexport.py:2` ("written atomically"), all to
  user-chosen folders. Documented pitfall in the maintainer's local PyQt/Windows notes (not in the repo).
- Problem: on Windows, when an ACL denies file creation, CPython's mkstemp retries as long as `os.access`
  says the folder is writable (it ignores ACLs), up to `os.TMP_MAX` = 2147483647 times -> the GUI thread
  hangs. Plausible real triggers (UNVERIFIED): Controlled Folder Access, read-only network shares, folders
  where a standard user may create folders but not files.
- Evidence: P6 - with `icacls <scratch folder> /deny <me>:(WD)`, `write_text_atomic(folder/'export.autopress.json')`
  was still running when the 15 s timeout killed it (exit 124); `os.TMP_MAX` printed 2147483647.
- Fix: create the temp file with `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` on a uuid name and turn the first
  PermissionError into StorageError (no mkstemp); same helper for save_png and the CSV export.

### T08 [major] `resolve_attention` must update a history record, HistoryStore cannot
- Where: `autopress/runner/engine.py:111-114` ("update the queue item and the latest history record of this
  run"), SPEC 2.2 (SPEC.md:97), SPEC 6.4.3 (SPEC.md:887); `autopress/codes/history.py:17-62` (append,
  records, latest, is_done, query, games, remove, clear, prune_evidence - no update);
  `tests/fakes.py:475-477` (the fake only changes the queue).
- Problem: G4 cannot edit G1's file; the only legal route is `remove([id])` + `append(new)`, which rewrites
  the file and moves the record to the end (changing "latest" semantics if another record exists). The fake
  already behaves differently, so G4 and G6 (history page) will disagree.
- Fix: add `HistoryStore.update(record_id: str, **changes) -> AttemptRecord` (atomic rewrite, same id,
  `finished_at` kept) to the G1 stub, snapshot and FakeHistoryStore before the groups start.

### T09 [major] No way to restart or reconfigure the OCR service
- Where: `autopress/ocr/service.py:61-67` (`start()` "idempotent", `shutdown()` "safe to call twice"),
  SPEC 6.4.5 (SPEC.md:896 重新啟動引擎, threads, warm-up), SPEC 5.6 (ocr settings), SPEC 2.8 step 4
  (`RunSession(queue, history, ocr)` keeps the instance).
- Problem: whether `start()` after `shutdown()` starts a new worker is undefined, and new settings
  (enabled, threads, det_side) cannot be passed in. The natural G5 workaround - build a new OcrService and
  assign `ctx.ocr` - leaves RunSession on the old, shut-down service, so every OCR step of the next run fails.
- Fix: add `OcrService.restart(settings: OcrSettings | None = None)` (same object, new worker, DISABLED when
  not enabled) and state that `ctx.ocr` is never replaced.

### T10 [major] `split = separator` can never split codes of formats without groups
- Where: `autopress/codes/normalize.py:29-38` (separators dropped, `fmt.separator` re-inserted only between
  `fmt.groups`), `normalize.py:59-64` (`split_code`), SPEC 5.3 type_code (SPEC.md:744), R5 (SPEC.md:44),
  docs/requirements.md ("依分隔符或固定字數拆段").
- Problem: for generic / hoyoverse / custom formats (no groups) the stored code has no separators, so
  SEPARATOR mode returns one segment: the whole code goes into the first box and the profile still
  validates (`Step.validate` only checks that `separators` is non-empty). With groups, SEPARATOR is the same
  as FIXED. Variable-length segments (e.g. 4-6-2) cannot be entered at all.
- Fix: split the normalized `CodeItem.raw` (or store segment boundaries at import) in SEPARATOR mode, or
  keep separators in `code` for groupless formats and strip them only for typing; validate/preflight
  warning for `split=separator` with `code_format.groups == []`; e2e case with unequal segments.

### T11 [major] G6 cannot build or test the Codes page while G7's RunFlow is a stub
- Where: SPEC 0.4 (SPEC.md:21-22 "Do not wait for other groups"), SPEC 6.4.1 (SPEC.md:855-860, page-owned
  RunFlow, `overlays.pick("region")`), `autopress/ui/codes_page.py:6`, `tests/ui_fallback.py:1-7`
  (fallbacks for G5 modules only).
- Problem: `RunFlow.__init__` and `overlays.pick` raise NotImplementedError until G7 lands. If G6 creates
  the RunFlow in `CodesPage.__init__` (the obvious reading), `CodesPage(ctx)`, all G6 must-cover tests
  (SPEC 8.2) and `tools/snap_widget.py autopress.ui.codes_page:CodesPage` fail.
- Fix: state "create RunFlow lazily on first use and show 尚未實作 when it raises NotImplementedError", or
  add FakeRunFlow / a pick() stand-in to the A1 fallbacks.

### T12 [major] Planned G3 tests cannot run under the forced offscreen platform
- Where: SPEC 8.2 G3 (SPEC.md:983: "client_rect/window_info of an own window", "hotkeys
  register/1409/unregister (own window, no input)" outside realinput), `tests/conftest.py:29-31`
  (offscreen for every non-realinput run).
- Problem: offscreen Qt windows have no HWND, so the natural test (`QWidget().winId()` -> client_rect /
  RegisterHotKey) fails with an invalid handle; G5's `build_context` test with the real GlobalHotkeys has the
  same issue (MainWindow attaches to winId()).
- Evidence: P4 - offscreen `QMainWindow().winId()` == 1, `IsWindow(1)` == False.
- Fix: tell G3 to create a hidden native window with ctypes (CreateWindowExW without WS_VISIBLE, or an
  HWND_MESSAGE window for hotkeys) or a `clean_env` child process; on Windows the offscreen plugin still uses
  QEventDispatcherWin32, so WM_HOTKEY should reach the native event filter (UNVERIFIED).

### T13 [major] `det_side 1920` for large reads is unmeasured and can lose small text
- Where: SPEC 5.3 (SPEC.md:751-752 "whole-client reads of clients larger than 1280 px use det_side 1920"),
  `autopress/ui/ocr_review.py:6-8` (det_side 1920 for images > 1920 px), ocr.md 1 and 3.4 (max1920 only in the
  latency table; the accuracy tables use min/736 and max960).
- Problem: a larger detector input does not mean better detection: in sparse UIs (a redeem dialog on a dark
  background, a web page at 100 % zoom) small text disappears.
- Evidence: P5 `crit_ocr_ctrl4.py` - sparse 1920x1080 scene (one code line + a boxed button label), dark and
  light: det 960 found 2/2 lines at 14, 18, 22 and 28 px; det 1920 found 0/2 at 14 px, 1/2 at 18 px, 2/2 only
  from 22 px. `crit_ocr_ctrl3.py`: detector boxes for a 14/16 px scene fell 2 -> 1 -> 0 -> 0 at det
  960/1280/1600/1920. A dense 5-line scene was 5/5 at both (`crit_ocr_ctrl2.py`), so the effect is
  scene-dependent - exactly why the rule needs a benchmark.
- Fix: use det_side 960 for every read until a U2-style benchmark (1280-2560 px clients, sparse and busy)
  supports something else; for large clients prefer a user region or tiling; let click_text retry with 2x
  crops instead of a larger det_side.

### T14 [major] Resuming with the mouse re-pauses the run (no grace period)
- Where: SPEC 2.6 (SPEC.md:151 resume resets the baseline; SPEC.md:157-158), `autopress/win32/input.py:133-142`
  (`dwTime > max(last injection, baseline) + slack_ms`, slack 200 ms), SPEC 11.9 (detector never fired with
  real input).
- Problem: the baseline is reset once when resume() arrives. The hand movement after clicking 繼續 on the
  mini bar (or an F8 press held > 200 ms) is newer than baseline + 200 ms, so the next guard check or wait
  slice raises UserActivity and the run pauses again with 「偵測到滑鼠或鍵盤操作」. Start has a countdown;
  resume has none. (Reasoning from the documented rule; not measured.)
- Fix: resume through a short countdown (reuse CountdownOverlay, 2 s) and reset the baseline at its end, or
  ignore input for N ms after resume; realinput test: click the bar, move the mouse, expect no re-pause.

### T15 [major] A shared profile can run arbitrary commands
- Where: `autopress/models.py:493-501` (KEY_NAMES include "Win"), `models.py:513-532` (key steps accept any
  combo; `validate_hotkey` forbids Win only for hotkeys), SPEC 2.7.1 (SPEC.md:161-163), SPEC 6.4.2
  (SPEC.md:879-880, a plain summary is the only import check), `TargetMatch.allow_same_process`.
- Problem: the guard only checks that the foreground window belongs to the target (or to its process).
  A profile with target exe "explorer.exe" + title mode "any" (matches any open File Explorer window,
  class CabinetWClass - e.g. the Downloads folder the user just opened; the desktop "Program Manager" is a
  WS_EX_TOOLWINDOW and is filtered out, checked on this PC), `allow_same_process: true`, steps key "Win+R",
  type_text "powershell ...", key "Enter" passes every check: the Run dialog is an explorer.exe window.
  Profiles are meant to be shared on Discord/Bahamut by non-technical users.
- Fix: reject "Win" in key steps (Step.validate ERROR); deny-list or hard-warn targets such as explorer.exe,
  cmd.exe, powershell.exe, pwsh.exe, WindowsTerminal.exe, conhost.exe, mmc.exe, regedit.exe, taskmgr.exe;
  show key and type_text steps verbatim and highlighted in the import summary; never import
  `allow_same_process: true` without an explicit tick.

### T16 [minor] rapidocr shrinks every input above ~2000 px before detection and recognition
- Where: SPEC 5.3 (SPEC.md:743 auto upscale "retry at 2x when ... the region is <= 1280x720"), ocr.md 4 recipe
  (no `Global.max_side_len`), rapidocr `config.yaml:8-10` (`use_preprocess_img: true`, `max_side_len: 2000`),
  `rapidocr/main.py:319-327` and `:345` (recognition crops come from the shrunk image).
- Problem: a 2x upscale of a 1280x720 region (2560x1440) is shrunk back to 1984x1120 (about 1.55x); 4K
  screenshots are read at 0.52x. Neither SPEC nor engine.py mentions it.
- Evidence: P5 - `resize_image_within_bounds` gives (1120, 1984) for 2560x1440 and 3840x2160 inputs.
- Fix: set `Global.max_side_len` explicitly in OcrEngine (and re-benchmark), or cap auto-upscale to regions
  whose doubled size stays below the limit; document it in engine.py.

### T17 [minor] Per-call overrides in rapidocr are sticky; per-call det_side needs internals
- Where: `autopress/ocr/engine.py:41-45` (`det_side` overrides Det.limit_side_len "for this call"),
  `rapidocr/main.py:93-120` (`__call__` has no limit_side_len), `main.py:287-317` (`update_params` writes into
  the instance).
- Problem: G2 must set `text_det.limit_side_len` (internal attribute, exists only after the det model loads)
  and restore it; any rapidocr call override also persists.
- Evidence: P5 `crit_ocr_ctrl3.py` - one `engine(img, use_rec=False)` call disabled recognition for all later
  calls of that engine (texts empty although boxes were found).
- Fix: document "set and restore in finally; never pass rapidocr call overrides"; add a test alternating
  det_side values; list `text_det` in the pinned-internals note of ocr.md 5.

### T18 [minor] OCR latency understated; OCR worker shutdown can crash at exit
- Where: SPEC 2.3 (SPEC.md:105 "up to ~0.5 s"), ocr.md 3.4 (1396 ms full-HD at max1920, 4495 ms live
  desktop), `autopress/ocr/service.py:4` (QThread or threading.Thread), `shutdown(timeout_s=2.0)`, SPEC 2.8
  step 8.
- Problem: an inference can outlast the 2 s shutdown; if G2 chooses a QThread, destroying it while running
  aborts the process ("QThread: Destroyed while thread is still running").
- Fix: correct the number; require a daemon `threading.Thread` for the OCR worker (or wait for the current
  job at exit); test shutdown during a slow fake inference.

### T19 [minor] Forward compatibility loses data while keeping the newer version number
- Where: `autopress/models.py:9-13` ("re-saving a profile written by a newer version loses nothing"),
  SPEC 5.9 (SPEC.md:818-821).
- Problem: only unknown step TYPES survive; unknown keys anywhere else are dropped, but `schema_version`
  stays at the newer value, so the newer app later trusts a file that lost its fields.
- Evidence: P1 - newer profile (`schema_version` 2): top-level `loop` and click_point `new_param` dropped,
  `schema_version` 2 kept, unknown step type kept.
- Fix: keep unknown keys (capture extras in `from_dict`, merge in `to_dict`) or write the current
  `schema_version` on save and warn before saving a newer profile.

### T20 [minor] A corrupt recorded point silently becomes a click at the client's top-left
- Where: `models.py:1879-1905` (`from_dict` falls back field by field), `models.py:1259-1262`
  (`missing_setup` only checks None).
- Evidence: P1 - point `{"dx": "abc", "dy": null, "rx": "?", "ref_w": 0}` loads as ClientPoint(0, 0, ..., 1x1);
  `missing_setup()` is empty; `resolve_point((1000, 500, 1280, 720), p)` -> (1000, 500).
- Fix: when dx/dy/rx/ry of a ClientPoint/ClientRegion fail to load, treat the whole value as None
  (position not set) so preflight blocks the run.

### T21 [minor] Lists with invalid elements shrink and change meaning
- Where: `models.py:1789-1799` (`_convert` drops bad list elements), `Settings.minibar_pos` (`models.py:1405`),
  `CodeFormat.groups` (`models.py:721`).
- Evidence: P1 - `minibar_pos [1, "a"]` -> `[1]` (neither `[]` nor `[x, y]`; `pos[1]` raises in G7);
  `groups [5, "x", -1]` -> `[5, -1]` (positions shift).
- Fix: for positional lists (minibar_pos, groups, group_sizes, quad) reject the whole list when any element
  is invalid.

### T22 [minor] The data-folder fallback banner cannot be implemented
- Where: SPEC 7.1 (SPEC.md:941 「無法寫入資料資料夾 {path}，改用 {fallback}」), `paths.py:142-159` (only logs).
- Problem: the UI cannot learn that a fallback happened or which folder was intended.
- Fix: the cached `resolve_data_dir()` of T03 returns `(path, intended_path or None)`.

### T23 [minor] Profile import preview has no read-only loader
- Where: SPEC 6.4.2 (SPEC.md:879-880: show `describe_actions()` and save only after 匯入),
  `storage.py:188-199` (`import_file` reads AND saves).
- Problem: G7 has to re-implement read + `profile_from_dict` (and hits T06) to show the summary first.
- Fix: add `ProfileStore.read_file(path) -> Profile` (no save, no rename) and `import_profile(profile) ->
  Profile` (id clash handling + save).

### T24 [minor] Signal signatures are not enforced
- Where: SPEC 0.3 (SPEC.md:17-20 "same Qt signals ... enforces this"), `tests/test_interfaces.py:121-123`,
  `tests/interface_snapshot.json` (signal names only).
- Problem: changing `progress(int, int, float)` to `(int, int)`, or emitting None into a float slot, passes the
  contract test and breaks G7 at integration.
- Fix: an A1 test with the expected `QMetaMethod.methodSignature()` of every signal from SPEC 4.3 (the
  snapshot itself must not be regenerated).

### T25 [minor] `docs/review/*` has no owner, so the ownership gate fails
- Where: SPEC 3.2 table (SPEC.md:205-240), `tools/check_ownership.py`, SPEC 10.3 step 3 (clean ownership check).
- Evidence: after another reviewer wrote `docs/review/spec_critique_product.md`, `check_ownership.py` printed
  "docs/review/spec_critique_product.md: no owner in SPEC.md ... 1 problems" (exit 1); this file adds a second.
- Fix: add a `docs/review/*` | ORCH row.

### T26 [minor] `allow_same_process` relaxes focus but not the click check
- Where: SPEC 2.7.1 (SPEC.md:161-163), `autopress/win32/input.py:67-73`.
- Problem: a redeem dialog opened as another top-level window of the same process (the reason for the flag)
  can be focused, but clicks on it fail PointNotOnTarget and coordinates are still resolved against the
  original window's client rect.
- Fix: with the flag, accept a root window of the same pid for clicks and resolve against the current
  foreground window of that pid - or drop the flag from the MVP.

### T27 [minor] Regex text and "|" alternatives conflict
- Where: `models.py:1036-1045` (validation splits on "|" before compiling), `autopress/ocr/textfind.py:4-8`,
  `textutil.split_alternatives`.
- Problem: a normal regex such as `^(OK|確定)$` is split into `^(OK` and `確定)$` and rejected.
- Fix: no alternative splitting in REGEX mode (regex has its own `|`).

### T28 [minor] Clipboard and IME restore are not required on interruption
- Where: `autopress/win32/input.py:83-94` (type_text), SPEC 2.3 (waits go through RunControl.sleep, whose
  tick may raise).
- Problem: StopRequested / UserActivity can be raised inside the `sleep(restore_clipboard_ms)` or between VK
  characters. Without try/finally the code stays on the clipboard and the user's previous clipboard (e.g. an
  image) is lost, or the target's IME stays closed.
- Fix: state "restore the clipboard snapshot and the IME state in finally, also on InjectionAborted /
  StopRequested"; realinput test with a stop during the restore delay.

### T29 [minor] Shutdown during a run loses the final bookkeeping
- Where: SPEC 2.6 table (SPEC.md:154 "app exit during a run ... PENDING / REVIEW"), `runner/engine.py:126-128`.
- Problem: queue/history updates happen in GUI-thread slots for queued Runner signals; `shutdown()` blocks the
  GUI thread in the join and the app then exits, so the last `code_finished` / `finished` are never
  delivered. queue.json keeps RUNNING and the next start marks it REVIEW even when the code was interrupted
  before submit.
- Fix: after the join call `QCoreApplication.sendPostedEvents(session)` (or apply the final result
  synchronously) before `queue.save()`.

### T30 [minor] Step tests and preview bypass the run safety model
- Where: SPEC 2.7.4 (SPEC.md:167 runs only with click + countdown; hotkeys only during runs), SPEC 6.4.2
  (SPEC.md:873-874 測試此步驟), `autopress/runner/preview.py:16-21` ("covered by another window"), SPEC 7.2
  `capture_blank`.
- Problem: test_step sends real input with no countdown and no F9; preview and preflight evaluate "covered"
  and "blank" while AutoPress's own main window usually covers the target (the user just clicked in it), so
  marks turn red and the blank check samples AutoPress pixels.
- Fix: 1-2 s countdown + F9 for real step tests; preview/preflight ignore AutoPress HWNDs (hide own windows or
  skip them like the picker does) or bring the target to the front first.

### T31 [minor] `--selftest` QApplication ownership and OPENBLAS placement are ambiguous
- Where: `autopress/ui/app.py:16-26`, `autopress/selftest.py:4-8`, SPEC 2.8 step 1 and SPEC.md:181-182.
- Problem: who creates the QApplication in selftest mode is undefined; if `main()` calls
  `create_application()` first, `selftest.run()` creating its own raises "A QApplication instance already
  exists". OPENBLAS_NUM_THREADS is set in `create_application()`, which is too late when app.py imports
  OcrService at the top (`ocr/service.py:20` imports numpy at module import; so do `runner/backend.py:14`,
  `ocr/imageio.py:10` and the Codes page stub).
- Fix: set OPENBLAS in `main.py` / `__main__.py` before importing autopress.ui.app; `main()` dispatches
  `--selftest` before `create_application()`; `selftest.run()` uses `QApplication.instance() or QApplication(...)`.

### T32 [minor] restart_as_admin races the single-instance lock
- Where: `autopress/win32/elevation.py:54-57`, SPEC 2.8 step 2 (QLockFile), SPEC 6.4.3 (restart_admin + quit).
- Problem: the elevated instance starts while the current one still holds the lock; if quitting takes longer
  than the new process needs to reach the lock (OCR shutdown up to 2 s), the new instance shows
  「AutoPress 已在執行中」 and exits - no instance left. (Not measured; 11.4 says restart is untested.)
- Fix: pass `--wait-lock` to the elevated instance and use `QLockFile.tryLock(10000)` then, or unlock before
  ShellExecute.

### T33 [minor] Tick wrap-around and SendInput results are not specified
- Where: `autopress/win32/input.py:128-142`, SPEC 9 (check return values).
- Problem: GetTickCount / GetLastInputInfo are 32-bit milliseconds (wrap after 49.7 days of uptime); the
  documented `>` comparison breaks across the wrap. Nothing says what to do when SendInput returns fewer
  events than sent (secure desktop, UAC prompt, locked screen).
- Fix: wrap-safe comparison `((a - b) & 0xFFFFFFFF) < 0x80000000`; raise InjectionAborted (localized) when
  SendInput returns less than n.

### T34 [minor] OCR thread default loads every core during the game
- Where: `models.py:1375` (`OcrSettings.threads = -1`), ocr.md 3.4 (4 threads: 220 ms vs 195 ms default at
  640x360).
- Problem: ocr_check / click_text poll every 500 ms while the game runs; -1 uses all cores for ~10 % speed,
  against the requirement that the tool should not affect the game.
- Fix: default 4 (or physical cores / 2).

### T35 [minor] Code extraction is cubic on the GUI thread
- Where: `autopress/codes/extract.py:11-20` ("every window of space-separated tokens"),
  `docs/research/scripts/ocr/ocr_common.py:164-174` (itertools.combinations + join), SPEC 6.4.1 (live
  candidates in PasteDialog).
- Problem: a pasted 1000-word paragraph gives ~500k windows, each joined and normalized, on every edit.
- Fix: stop growing a window once its length without spaces/separators exceeds `fmt.max_len`; debounce the
  live preview.

### T36 [minor] CSV export allows formula injection
- Where: `autopress/codes/csvexport.py:1-23`.
- Problem: messages come from OCR of arbitrary pages/games and codes may start with "-" or "+"; Excel
  evaluates cells starting with `=`, `+`, `-`, `@`.
- Fix: prefix such cells with an apostrophe (OWASP CSV injection guidance).

### T37 [minor] 重試失敗 also re-runs possibly redeemed REVIEW items
- Where: `autopress/codes/queue.py:106-108` (FAILED and REVIEW with attempts > 0 -> PENDING), SPEC 5.7
  (SPEC.md:792, REVIEW "not run until confirmed").
- Fix: restrict `retry_failed()` to FAILED; give REVIEW items their own explicit action.

### T38 [minor] Attention while the main window is hidden; F9 during the countdown
- Where: SPEC 2.4 steps 3-5 (SPEC.md:112-114), SPEC 6.4.3 (attention panel on the Run page).
- Problem: the attention panel lives in the hidden main window and nothing says when it is shown; F9 is wired
  to `session.stop` (a no-op before `start`) although step 4 says F9 cancels the countdown.
- Fix: define that a hard pause / attention restores the main window (or the bar shows the attention
  actions); route F9 to `CountdownOverlay.cancel()` while counting down.

### T39 [minor] dpi.py says "import after QApplication"
- Where: `autopress/win32/dpi.py:4` vs `autopress/win32/__init__.py:5-6` ("importing any module here must not
  change process state").
- Problem: read literally it forces lazy imports in capture, overlays and every importer.
- Fix: "call after QApplication exists; importing is side-effect free".

### T40 [minor] Elevated AutoPress loses drag-and-drop from Explorer
- Where: SPEC 6.4.1 (drag-drop import), SPEC 6.4.3 (restart_admin), Help troubleshooting.
- Problem: after the elevated restart, UIPI blocks drag-and-drop from medium-integrity Explorer onto the
  Codes page (UNVERIFIED on this PC). Users will think import broke.
- Fix: mention it in Help 系統管理員權限 and in the restart prompt.

### T41 [minor] Environment fact: the project is already a git repository
- Where: task context ("NOT a git repo"), SPEC 10.3 step 6 (create the private repo after confirmation).
- Evidence: `git status -sb` -> `## main...origin/main`; 2 commits; an `origin` remote on GitHub is configured;
  SPEC.md, autopress/, tests/, tools/ untracked.
- Fix: update the orchestration facts (backup rule, R6 step) to match.

## Checked and found consistent

* Win32 constants and recipes in the stubs match the research: INPUT 40 bytes / `ULONG_PTR = c_size_t`,
  pixel-centre ABSOLUTE|VIRTUALDESK formula, EXTRA_TAG 0x41505253, EXTENDED_VKS (+ MapVirtualKeyEx E0 check),
  atomic SendInput per character, MOD_NOREPEAT, app-wide filter returning `(True, 0)`, `mss.MSS()` only after
  QApplication, one Grabber per thread, physical pixels everywhere, client-relative offset + ratio math.
* rapidocr 3.10.0 / onnxruntime 1.32.0 and the rest of `requirements.txt` are installed in `.venv` as pinned;
  `paths.ocr_model_dir()` matches the frozen layout of ocr.md 6.
* `from_dict` survives junk settings sanely (invalid hotkeys -> F8/F9, ranges clamped, unknown enums -> default,
  policy min/max swapped); `clone()` of a profile with every step type round-trips exactly (P1).
* No glob overlap among the planned file names in SPEC 3.2.

## Not verifiable here

* WDA_EXCLUDEFROMCAPTURE with mss/BitBlt (T01), WM_HOTKEY delivery to a hidden or offscreen-process HWND
  (T12, SPEC 11.2), real Controlled Folder Access behaviour (T07), real 125/150 % DPI, real games and
  anti-cheat, the UAC restart race (T32), the resume re-pause (T14; reasoning from the documented rule).
