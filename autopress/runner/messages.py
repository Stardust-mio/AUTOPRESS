# OWNED BY G4
"""Localized runner texts (SPEC section 7.1 and 7.2), as functions so ``tr`` is only called when
a text is shown or persisted (never at import time). Persisted messages (queue / history) are
created with the language active at write time (SPEC 5.7)."""

from __future__ import annotations

from ..i18n import format_duration, tr


def _num(v: float) -> str:
    return f"{v:g}"


# ----------------------------------------------------------------------------- pauses / attention

def target_not_found(target: str) -> str:
    return tr(f"找不到目標視窗：{target}。請先開啟遊戲或兌換網頁，或重新選擇視窗。",
              f"Target window not found: {target}. Open the game or redeem page first, or pick the window again.")


def target_closed() -> str:
    return tr("目標視窗已關閉，已暫停。重新開啟後按「繼續」。",
              "The target window was closed; paused. Reopen it and press Resume.")


def focus_lost() -> str:
    return tr("目標視窗失去焦點，已暫停。切回目標視窗後按「繼續」(F8)。",
              "The target window lost focus; paused. Switch back and press Resume (F8).")


def focus_failed() -> str:
    return tr("無法把目標視窗切到最前面，已暫停。請手動點一下目標視窗後按「繼續」(F8)。",
              "Could not bring the target window to the front; paused. Click the target window once, "
              "then press Resume (F8).")


def user_input() -> str:
    return tr("偵測到滑鼠或鍵盤操作，已暫停以免輸入到錯誤的地方。按「繼續」(F8) 接著做。",
              "Mouse or keyboard input detected; paused so nothing goes to the wrong place. Press Resume (F8).")


def point_covered(title: str) -> str:
    return tr(f"點擊位置被「{title}」遮住，已暫停。請移開該視窗後按「繼續」。",
              f'The click position is covered by "{title}"; paused. Move that window away and press Resume.')


def input_blocked() -> str:
    return tr("Windows 擋下了模擬輸入（可能出現了 UAC 視窗、螢幕已鎖定，或目標權限較高），已暫停。處理後按「繼續」。",
              "Windows blocked the simulated input (UAC prompt, locked screen or a higher-privilege target?); "
              "paused. Fix it and press Resume.")


def title_changed() -> str:
    return tr("目標頁面標題已改變（可能切換了分頁），已暫停。切回兌換頁面後按「繼續」。",
              "The target page title changed (another tab?); paused. Switch back to the redeem page and press Resume.")


def size_changed(a: str, b: str) -> str:
    return tr(f"視窗大小改變了（{a} → {b}），已暫停。請先預覽點位，確認無誤後按「繼續」。",
              f"The window size changed ({a} → {b}); paused. Preview the positions, then press Resume.")


def capture_blank() -> str:
    return tr("擷取到的畫面是全黑或單色（可能是獨佔全螢幕或螢幕已鎖定）。請把遊戲改成「無邊框視窗」或視窗模式後再試。",
              "The capture is black or uniform (exclusive fullscreen or a locked screen?). Switch the game to "
              "borderless or windowed mode and try again.")


def unknown_result(text: str) -> str:
    return tr(f"無法判讀結果：「{text}」。請選擇結果，或把文字加入關鍵字。",
              f'Could not recognise the result: "{text}". Pick the result or add the text as a keyword.')


def invalid_streak(n: int) -> str:
    return tr(f"連續 {n} 筆被判定無效，可能是輸入方式有誤（輸入法、大小寫、拆段），已暫停。請用「測試一筆」檢查輸入框內容。",
              f'{n} codes in a row were judged invalid - the input method may be wrong (IME, letter case, split); '
              'paused. Use "Test one" and check the input box.')


def unexpected_error(reason: str) -> str:
    return tr(f"發生未預期的錯誤，已暫停並記錄在紀錄檔（{reason}）。",
              f"An unexpected error occurred; paused and logged ({reason}).")


def paused_by_user() -> str:
    return tr("已暫停，按「繼續」(F8) 接著做。", "Paused. Press Resume (F8) to continue.")


def resumed() -> str:
    return tr("繼續執行", "Resumed")


# ----------------------------------------------------------------------------- stops / summary

def rate_limit_cooldown(seconds: float) -> str:
    return tr(f"偵測到「操作過於頻繁」，{_num(seconds)} 秒後重試這筆序號。",
              f"Rate limit detected; retrying this code in {_num(seconds)} s.")


def rate_limit_stop() -> str:
    return tr("偵測到「操作過於頻繁」，已停止。請稍後再試。", "Rate limit detected; stopped. Try again later.")


def failures_stop(n: int) -> str:
    return tr(f"連續 {n} 筆失敗，已停止。請檢查設定檔與目標視窗。",
              f"{n} failures in a row; stopped. Check the profile and the target window.")


def failsafe_stop() -> str:
    return tr("滑鼠移到螢幕左上角，已緊急停止。", "Mouse moved to the top-left corner: emergency stop.")


def unknown_stop(text: str) -> str:
    return tr(f"無法判讀結果「{text}」，依設定已停止。", f'Could not recognise the result "{text}"; stopped as configured.')


def stopped_by_user() -> str:
    return tr("已停止。", "Stopped.")


def completed(n: int) -> str:
    return tr(f"全部完成，共 {n} 筆。", f"All done: {n} codes.")


def ocr_not_ready(reason: str) -> str:
    return tr(f"文字辨識引擎沒有就緒，已停止：{reason}", f"The OCR engine is not ready; stopped: {reason}")


def code_started(i: int, n: int, code: str) -> str:
    return tr(f"第 {i} / {n} 筆：{code}", f"Code {i} / {n}: {code}")


def code_result(code: str, label: str, message: str) -> str:
    tail = f" - {message}" if message else ""
    return tr(f"{code}：{label}{tail}", f"{code}: {label}{tail}")


def unknown_steps_skipped(n: int) -> str:
    return tr(f"有 {n} 個較新版本的步驟無法執行，已略過。", f"{n} steps from a newer version cannot run and are skipped.")


# ----------------------------------------------------------------------------- queue messages (persisted)

def no_change_after_submit() -> str:
    return tr("送出後結果區沒有出現新的訊息（可能和上一筆的訊息相同）",
              "No new message appeared in the result area after submitting (it may be the same message as for "
              "the previous code)")


def failed_after_submit(reason: str) -> str:
    return tr(f"送出後的步驟失敗，請確認是否已兌換：{reason}",
              f"A step after submitting failed; check whether it was redeemed: {reason}")


def interrupted_after_submit() -> str:
    return tr("中斷於送出後，請確認是否已兌換", "Interrupted after submitting; check whether it was redeemed")


def run_interrupted() -> str:
    return tr("執行中斷，請確認是否已兌換", "The run was interrupted; check whether this code was redeemed")


def history_skip() -> str:
    return tr("紀錄顯示已兌換過", "History shows it was redeemed")


def no_text_read() -> str:
    return tr("未讀到任何文字", "No text was read")


# ----------------------------------------------------------------------------- step errors

def text_not_found(text: str) -> str:
    return tr(f"找不到文字「{text}」。請確認兌換視窗已開啟，或在設定檔調整要找的文字或搜尋範圍。",
              f'Text "{text}" was not found. Check that the redeem window is open, or adjust the text or search '
              'region in the profile.')


def text_skipped(text: str) -> str:
    return tr(f"沒有出現「{text}」，略過這一步", f'"{text}" did not appear; step skipped')


def wait_text_timeout(text: str, appear: bool) -> str:
    if appear:
        return tr(f"等待「{text}」出現逾時", f'Timed out waiting for "{text}" to appear')
    return tr(f"等待「{text}」消失逾時", f'Timed out waiting for "{text}" to disappear')


def typed_mismatch() -> str:
    return tr("輸入內容與序號不符（可能被輸入法改寫或權限阻擋）。請改用「貼上」或關閉注音後再試。",
              "The typed text does not match the code (IME or blocked input?). Use paste mode or turn the IME off "
              "and try again.")


def unmappable_char(ch: str) -> str:
    return tr(f"遊戲模式無法輸入字元「{ch}」（目前的鍵盤配置沒有這個鍵）。請改用「模擬鍵入」或「貼上」。",
              f'Game mode cannot type "{ch}" (no such key on the keyboard layout). Use simulated typing or paste mode.')


def clipboard_busy() -> str:
    return tr("剪貼簿被其他程式佔用，無法貼上序號。請稍後再試，或改用「模擬鍵入」。",
              "The clipboard is held by another program; the code could not be pasted. Try again or use simulated "
              "typing.")


def ocr_timeout() -> str:
    return tr("文字辨識逾時。請縮小搜尋範圍，或在設定中重新啟動文字辨識引擎。",
              "Text recognition timed out. Use a smaller search region or restart the OCR engine in Settings.")


def capture_failed(reason: str) -> str:
    return tr(f"無法擷取畫面：{reason}。目標視窗可能已關閉或移到螢幕外。",
              f"Cannot capture the screen: {reason}. The target window may be closed or off-screen.")


def region_outside() -> str:
    return tr("範圍在目標視窗外", "the region is outside the target window")


def ocr_failed(reason: str) -> str:
    return tr(f"文字辨識引擎無法啟動：{reason}。請重新下載完整的壓縮檔並解壓縮，或檢查防毒軟體是否隔離了檔案。",
              f"The OCR engine could not start: {reason}. Download and unzip the full package again, or check "
              "whether antivirus quarantined files.")


def position_not_set() -> str:
    return tr("尚未設定點擊位置", "The click position is not set")


def region_not_set() -> str:
    return tr("尚未設定結果範圍", "The result region is not set")


def system_shortcut(keys: str) -> str:
    return tr(f"「{keys}」是系統快捷鍵，設定檔不能使用", f"'{keys}' is a system shortcut; profiles cannot use it")


def unknown_step() -> str:
    return tr("較新版本的步驟無法執行", "This step is from a newer version and cannot run")


# ----------------------------------------------------------------------------- step test reports

def step_done() -> str:
    return tr("這一步執行完成", "The step completed")


def test_stopped() -> str:
    return tr("已停止測試", "Test stopped")


def would_click(x: int, y: int) -> str:
    return tr(f"會點擊 ({x}, {y})", f"Would click ({x}, {y})")


def clicked(x: int, y: int) -> str:
    return tr(f"已點擊 ({x}, {y})", f"Clicked ({x}, {y})")


def would_type(text: str) -> str:
    return tr(f"會輸入「{text}」", f'Would type "{text}"')


def typed(text: str) -> str:
    return tr(f"已輸入「{text}」", f'Typed "{text}"')


def would_press(keys: str) -> str:
    return tr(f"會按 {keys}", f"Would press {keys}")


def pressed(keys: str) -> str:
    return tr(f"已按 {keys}", f"Pressed {keys}")


def text_found(text: str, x: int, y: int) -> str:
    return tr(f"找到「{text}」於 ({x}, {y})", f'Found "{text}" at ({x}, {y})')


def text_present(text: str, present: bool) -> str:
    if present:
        return tr(f"畫面上有「{text}」", f'"{text}" is on the screen')
    return tr(f"畫面上沒有「{text}」", f'"{text}" is not on the screen')


def waited(seconds: float) -> str:
    return tr(f"等待 {_num(round(seconds, 2))} 秒", f"Waited {_num(round(seconds, 2))} s")


def wait_skipped() -> str:
    return tr("試跑不等待", "Dry run: no waiting")


def focused() -> str:
    return tr("目標視窗已在最前面", "The target window is in front")


def result_read(label: str, text: str) -> str:
    return tr(f"辨識結果：{label}（{text}）", f"Result: {label} ({text})")


# ----------------------------------------------------------------------------- preflight (SPEC 7.2)

def pf_target_elevated() -> str:
    return tr("目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的模擬輸入。請按「以系統管理員身分重新啟動 AutoPress」。",
              'The target runs as administrator; Windows silently blocks simulated input from normal programs. '
              'Click "Restart AutoPress as administrator".')


def pf_target_elevated_standard_user() -> str:
    return tr("此帳戶沒有系統管理員權限，無法對以系統管理員身分執行的程式輸入。若遊戲有網頁兌換頁，請改用網頁。",
              "This account cannot elevate, so it cannot send input to a program running as administrator. Use the "
              "game's web redeem page if it has one.")


def pf_elevation_unknown() -> str:
    return tr("無法讀取目標程式的權限（可能是系統或受保護程式）；若輸入沒有反應，請以系統管理員身分執行 AutoPress。",
              "Cannot read the target's privileges (system or protected program). If input has no effect, run "
              "AutoPress as administrator.")


def pf_ocr_loading() -> str:
    return tr("文字辨識引擎載入中，開始後會等待它就緒。", "The OCR engine is loading; the run waits until it is ready.")


def pf_ocr_disabled() -> str:
    return tr("這個設定檔需要文字辨識，但文字辨識已在設定中關閉。請到「設定」開啟文字辨識。",
              "This profile needs text recognition, but it is turned off. Turn it on in Settings.")


def pf_forbidden(exe: str) -> str:
    return tr(f"{exe} 是系統或命令列程式，AutoPress 不會對它輸入。請改選遊戲或兌換網頁的視窗。",
              f"{exe} is a system or command-line program; AutoPress never types into it. Pick the game or redeem "
              "page window instead.")


def pf_title_required() -> str:
    return tr("瀏覽器目標必須設定標題關鍵字（例如「兌換」），以免輸入到其他分頁。請重新選擇視窗或填寫標題關鍵字。",
              'A browser target needs a title keyword (e.g. "Redeem") so input never goes to another tab. Pick the '
              'window again or enter a keyword.')


def pf_target_exe_unknown() -> str:
    return tr("讀不到目標視窗的程式名稱，任何標題相符的視窗都可能被當成目標。請重新選擇視窗，或在設定檔把標題比對改成「標題完全相同」。",
              "The target window's program is unknown, so any window with a matching title could be used. Pick the "
              "window again, or set the profile's title match to 'Title equals'.")


def target_rebind(title: str) -> str:
    return tr(f"原本的目標視窗已關閉。找到另一個符合條件的視窗「{title}」：確認它是兌換頁面或遊戲後，按「繼續」改用這個視窗。",
              f'The original target window was closed. Another matching window was found: "{title}". If it is the '
              "redeem page or the game, press Resume to use it.")


def target_rebind_many(n: int) -> str:
    return tr(f"原本的目標視窗已關閉，有 {n} 個視窗符合條件，無法確定要用哪一個。請只留下兌換頁面或遊戲的視窗，再按「繼續」。",
              f"The original target window was closed and {n} windows match, so AutoPress cannot tell which one to use. "
              "Keep only the redeem page or game window open, then press Resume.")


def pf_target_not_set() -> str:
    return tr("尚未選擇目標視窗。", "No target window is selected.")


def pf_target_is_self() -> str:
    return tr("目標視窗是 AutoPress 自己，請改選遊戲或兌換網頁的視窗。",
              "The target is AutoPress itself; pick the game or redeem page window.")


def pf_target_multiple(n: int, title: str) -> str:
    return tr(f"有 {n} 個視窗符合目標條件，將使用「{title}」。", f'{n} windows match the target; "{title}" will be used.')


def pf_target_minimized() -> str:
    return tr("目標視窗目前縮到最小，開始時會先還原。", "The target window is minimized; it is restored when the run starts.")


def pf_size_changed(a: str, b: str, ratio: bool) -> str:
    if ratio:
        return tr(f"視窗大小與錄製時不同（{a} → {b}），將依比例換算；建議先預覽或重新對準",
                  f"The window size differs from the recording ({a} → {b}); positions are scaled. Preview or "
                  "re-align first")
    return tr(f"視窗大小與錄製時不同（{a} → {b}），位置依固定像素計算；建議先預覽或重新對準",
              f"The window size differs from the recording ({a} → {b}); positions keep fixed pixels. Preview or "
              "re-align first")


def pf_dpi_changed(a: int, b: int) -> str:
    return tr(f"目標視窗的縮放比例與錄製時不同（{a}% → {b}%），點位可能偏移；建議先「重新對準」。",
              f"The target's scaling differs from when the positions were recorded ({a}% → {b}%); positions may be "
              "off. Re-align first.")


def pf_points_missing(steps: str) -> str:
    return tr(f"還有位置或結果範圍尚未設定（第 {steps} 步）。", f"Some positions or result regions are not set (step {steps}).")


def pf_no_codes() -> str:
    return tr("沒有這個遊戲可執行的序號。請先在「序號」頁加入序號。",
              "There are no runnable codes for this game. Add codes on the Codes page first.")


def pf_unassigned(n: int) -> str:
    return tr(f"{n} 筆序號尚未指定遊戲，這次不會執行。", f"{n} codes have no game yet and will not run.")


def pf_no_result_check() -> str:
    return tr("沒有「辨識結果」步驟：無法判斷是否兌換成功，也無法偵測「操作過於頻繁」；結果會標為「已送出（未確認）」。",
              "No 'Read result' step: AutoPress cannot tell whether a code worked or detect rate limits; results "
              "are marked 'Submitted (unconfirmed)'.")


def pf_no_verify() -> str:
    return tr("「輸入序號」沒有設定核對範圍；若結果常被判定無效，請設定核對範圍檢查實際輸入的內容。",
              '"Type code" has no verify region; if codes keep failing as invalid, add one to check what was typed.')


def pf_untested() -> str:
    return tr("這個設定檔還沒有成功測試過，建議先按「測試一筆」。", 'This profile has not passed a test yet; try "Test one" first.')


def pf_fast_interval(a: float) -> str:
    return tr(f"每筆間隔只有 {_num(a)} 秒；太快可能被服務判定為頻繁操作。建議至少 2 秒。",
              f"Codes are only {_num(a)} s apart; services may treat this as too frequent. Use at least 2 s.")


def pf_daily_cap_reached(cap: int) -> str:
    return tr(f"今天已達每日上限 {cap} 筆。", f"Today's limit of {cap} attempts is reached.")


def pf_daily_cap_shortened(n: int) -> str:
    return tr(f"已依每日上限只排入 {n} 筆。", f"Only {n} codes were queued because of the daily limit.")


def pf_estimate(n: int, a: float, b: float, seconds: float) -> str:
    t = format_duration(seconds)
    return tr(f"共 {n} 筆，每筆間隔 {_num(a)}–{_num(b)} 秒，預估約 {t}。", f"{n} codes, {_num(a)}-{_num(b)} s apart, about {t}.")


def pf_more_errors(n: int) -> str:
    return tr(f"另有 {n} 個問題，請開啟設定檔查看。", f"{n} more problems; open the profile to see them.")
