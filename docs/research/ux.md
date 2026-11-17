# AutoPress - product & UX research (R3)

2026-11-17 · research agent R3 · survey, product definition, flows, design system and a static prototype.
Prototype: `docs/research/scripts/ux/prototype.py` -> PNGs in `docs/research/ux/` (section 8). Sources are listed in section 9 and cited as [n].
Survey statements carry sources. Lines marked **P** are design proposals, not facts.

## 1. Key takeaways
1. Today's redeemers each cover one thing. There are publisher-API bots and extensions for HoYoverse only [1][2][3][4][5][6], single-site userscripts [7][8] and per-game AHK scripts [9].
   Generic macro tools replay screen coordinates and break when the resolution or window changes [12][13], and they know nothing about codes or results. **The gap is a tool that is generic and also understands codes and results.**
2. The failures that come up again and again are typing into the wrong window [15][9][19], elevated targets silently ignoring input [20][21], anti-cheat and ToS risk [21][24], DPI and coordinate drift [25][12][13],
   black captures in exclusive fullscreen [26], OCR look-alike characters [16][27][28] and rate limits [29][7][8][1].
3. **P** Prefer the official web redeem page whenever one exists, because the game client is not touched at all [32][33]. Web templates come first in the gallery.
4. **P** Keep reliability visible at all times: an always-on status bar (foreground guard, interval, hotkeys, target), a pre-flight check, a dry-run overlay and a "test 1 code" button.
5. **P** Never ship code lists, guessers or brute force. One surveyed script tries every value for unknown characters [11]; AutoPress has no wildcard expansion by design.

## 2. Survey
### 2.1 Existing tools
| Tool (type) | How it works | Users like | Pain points | Src |
|---|---|---|---|---|
| genshin.py (API library) · hoyo-codes (code feed) · Kuma bot (HoYoLAB API) | hoyo-codes scrapes code pages and verifies each code with a real redemption through genshin.py; Kuma redeems codes from fan-wiki lists for linked accounts 4x/day | zero effort | HoYoverse only, needs account linking, depends on scraped lists | [1][2][3] |
| Traveler Assistant / HoYoverse CodeEnter (extensions) | right-click selected code -> redeem for current account / type code -> official page opens in popup | 1 click in browser | fan-made, HoYoverse only; Traveler Assistant needs a HoYoLAB login | [4][5] |
| GenshCode (extension) | ships its own code list (implied by the review) | automatic | only review: "not a single code has been added" (3.0 stars) | [6] |
| Batch Register Steam Keys (userscript) | comma-separated or multi-line keys, about 5 s wait per key "to avoid banning" | bulk paste | no syntax check; per-key report not described | [7] |
| ASF background redeemer (Steam) | `name<TAB>key` file; RateLimited -> pause 1 h and resume; writes `.keys.used/.unused/.invalid` | queue, history, resume | Steam only, power users | [8] |
| MTGA Code Slammer (AHK) | codes hard-coded in the script; Ctrl+J start, Ctrl+Esc stop, stops when the game loses focus | dead simple | edit source to add codes; compiled exe goes stale; AHK v1 only | [9] |
| Kingshot / Pokémon redeemers (scripts) | CLI + JSON of player IDs (signed REST calls) / user solves captcha and copies cookies; "?" chars brute-forced | bulk for many IDs | technical setup; brute force | [10][11] |
| TinyTask (recorder) | replays absolute screen coordinates | trivial to record | "record on 1920x1080, play on 1280x720, everything breaks"; moved window = missed clicks | [12][13] |
| Pulover's Macro Creator | records relative to window or screen; image/pixel search; control commands in background windows; if/loops; exports AHK | power, free | steep for non-technical users | [14] |
| AutoHotkey Send / ControlSend | Send goes to the active window; ControlSend targets a window but bypasses normal keyboard processing and "sometimes doesn't work" | flexible | scripting required | [15] |
| PowerToys Text Extractor | Win+Shift+T region -> Windows OCR -> clipboard; needs OCR language packs; "proof read the output" | instant | language packs; no code awareness | [16] |
| ShareX OCR | Windows OCR, local; Win10 1903+; single-line, scale-factor and silent-copy options | options | same engine limits | [17] |
| Umi-OCR | offline PaddleOCR/RapidOCR; screenshot, paste and batch OCR; ignore regions; HTTP/CLI API; MIT | offline, batch | separate app | [18] |

### 2.2 Failure modes -> requirements
| Failure mode | Evidence | AutoPress requirement (**P**) |
|---|---|---|
| Keys land in the wrong window | Send targets whatever is active; slow sends risk focus shifts [15]. The Windows foreground lock flashes the taskbar instead of activating [19]. MTGA script self-stops on focus loss [9] | foreground guard before every input burst; run starts from the user's click, then a countdown |
| Elevated target ignores input | SendInput is subject to UIPI and the failure is not reported [20]; UAC protects elevated programs [21] | detect integrity level; warn with "以系統管理員身分重新啟動" |
| Game blocks input / anti-cheat | GameGuard/HackShield games block AHK [21]; injected events carry LLKHF/LLMHF_INJECTED [22][23]; HoYoverse warned that dialogue-skip macros can mean bans and currency removal [24] | honest ToS copy; web pages first; never during gameplay |
| DPI / resolution drift | recorders replay absolute coordinates [12][13]; system DPI scaling distorts coordinates on non-primary screens [25] | per-monitor-v2 DPI aware; client-relative fractions; OCR text anchors; preview overlay |
| Black capture | exclusive fullscreen prevents capture; borderless works [26] | detect uniform/black frames -> "請改用無邊框視窗" banner |
| OCR misreads | Text Extractor: proofread [16]; Steam: "I, L, and 1 can look alike, as can V and Y, 0 and O" [27]; Nintendo omits O, I, Z [28] | confusable highlighting, preset charsets, editable cells |
| Rate limits | Steam "too many recent activation attempts", anecdotal 30-60 min, retrying resets the timer [29]; ASF pauses 1 h [8]; HoYoLAB cooldown retcode -2016 [1] vs a guide claiming no web cooldown [33] | per-profile interval + jitter; stop or cool down on rate-limit text |
| Stale lists, duplicates | GenshCode review [6]; ASF used/unused files [8] | local history, dedupe, never ship code lists |
| Chinese IME rewriting keystrokes | **no source found** - hypothesis | type via Unicode or paste; warn when an IME is in native mode (R1/R2 to test) |

### 2.3 What a general tool must offer
Import from any text or image with presets, dedupe and history. Profiles that are resolution independent (window-relative points plus OCR anchors), have a test button and a dry-run preview.
Result reading with editable multilingual keyword groups. Rate limits with stop-on-rate-limit. Hard stops (hotkeys, failsafe corner, physical-input pause, foreground guard). Profile sharing as a file.
It must work for web pages and game dialogs alike, offline, and without accounts, cookies or APIs.

## 3. Code formats -> extraction presets
| Preset | Pattern after normalisation | Case | Where / notes | Src |
|---|---|---|---|---|
| HoYoverse (原神/星鐵/絕區零) | `[A-Za-z0-9]{6,16}`: ZZZ888 (6), 64GM5HQF2F (10), ZENLESSGIFT (11), mixed-case livestream codes like ComeNightorDay | preserve (guide: case-sensitive) | web: genshin.hoyoverse.com/en/gift, hsr.hoyoverse.com/gift, zenless.hoyoverse.com/redemption; log in, server, nickname; Genshin AR>=10, ZZZ Inter-Knot Lv>=5 | [32][33][34] |
| Wuthering Waves (鳴潮) | `[A-Za-z0-9]{6,20}` (WUTHERINGGIFT) | exact capitalisation | in-game only: Terminal > Settings > Other Settings > Redemption Code; Union Lv>=2 | [35] |
| Blue Archive (蔚藍檔案) | `[A-Za-z0-9]{6,20}` (THESKYOFUNITY0526 = 17) | "as written" | menu (top right) > Account > Coupon | [36] |
| MapleStory GMS (楓之谷) | generic | - | Cash Shop (non-Reboot) > Coupon; paste from Coupon Vault | [37] |
| Arknights (明日方舟) | generic | - | web redemption with UID; server-specific codes; source's link is wrong -> unclear | [38] |
| Steam | `[A-Z0-9]{5}(-[A-Z0-9]{5}){2}` (community: "usually 5-5-5") | not case-sensitive (community) | official: "single-use, unique, alphanumeric" | [30][31] |
| Xbox / Microsoft | `([A-Z0-9]{5}-?){4}[A-Z0-9]{5}` | - | "25-character digital code"; excluded-letter lists only on third-party sites (unverified) | [39] |
| Nintendo eShop | `[A-HJ-NP-Y0-9]{16}` | - | 16 characters; "not used ... such as O, I, Z, and hyphens" | [28] |
| 自訂 Custom | builder: length range, charset, group size, separator, regex | per profile | - | - |

**P** normalisation: NFKC (full-width Ａ－ -> A-), strip zero-width/BOM, map dash variants (‐‑‒–—−ー) to "-", trim, uppercase only for case-insensitive presets, dedupe on the normalised key.
**P** look-alike pairs to flag (never fix silently): 0/O/D/Q, 1/I/l/|, 2/Z, 5/S, 6/G, 8/B, U/V, V/Y [27]. Auto-correct only when the preset charset rules one reading out (Nintendo: O -> 0), and still flag it.
**P** auto-detect: run all presets, rank by match count and specificity, and show the winner in the 格式 combo so the user can override it.

## 4. Result messages and default keyword groups
Sourced strings are quoted with their source. P = proposed default keywords; the user can edit every group per profile.
| Class | en | zh-TW | zh-CN | ja | ko |
|---|---|---|---|---|---|
| success | P: redeemed, success | P: 兌換成功, 領取成功 | P: 兑换成功, 领取成功 | P: 交換しました, 受け取り | P: 교환 완료, 지급 |
| used | "Redemption code has been claimed already." [1]; "This Code Has Already Been Used" [40]; Steam DuplicateActivationCode [8] | 「已使用」[44]; P: 已被使用, 已兌換過 | P: 已被使用, 已兑换过, 已领取 | 「このコードは既に使用されています」[41]; P: 使用済み | 「이미 사용됨」[43]; P: 이미 사용 |
| invalid | "Invalid redemption code." / "...incorrectly formatted." [1]; "Invalid Product Code ..." [27] | 「無效」[44]; P: 錯誤, 不存在 | P: 无效, 不存在, 错误 | 「入力したシリアル番号は無効です」[42] | 「유효하지 않음」[43] |
| expired | "Redemption code has expired." [1] | P: 已過期, 已失效 | P: 已过期, 已失效 | P: 期限切れ, 有効期限 | P: 만료 |
| rate-limited | "Redemption is on cooldown." / "Visits too frequently." [1]; "There have been too many recent activation attempts ..." [29]; "operation frequency too high" [45] | P: 過於頻繁, 稍後再試 | P: 过于频繁, 请稍后再试 | P: しばらく時間をおいて | P: 잠시 후 다시 |
| region / level / cap | "...not available in the account's region.", level-too-low retcodes, "...reached max usage limit." [1]; AR 10 [33]; Inter-Knot Lv 5 [32] | P: 伺服器, 地區, 等級不足, 上限 | 「达到使用上限」[32]; P: 服务器, 等级不足 | 「使用上限」[46]; P: レベル, 地域 | P: 서버, 레벨 |

**P** matching: normalise both sides (NFKC, lowercase, no spaces) and test groups in order rate-limited > used > expired > invalid > region > success (the order is editable). Keywords must not overlap: use 已兌換過, not 已兌換.
**P** unknown result: in attended mode pause and show the OCR text with "加入關鍵字…". In unattended mode log it with an evidence crop and stop after 3 unknowns in a row.

## 5. Product definition
### 5.1 Personas
| Persona | Context | Needs | Risks |
|---|---|---|---|
| 小安, casual multi-game player (non-technical) | 3-10 codes per livestream in 2-3 games, often seen as screenshots | snip or paste and done; clear "成功 / 已使用"; reassurance about bans | wrong server or account; over-trusting the tool |
| 阿哲, key collector | bundles of 20-50 keys, photos of cards | photo OCR, dedupe, history, CSV | Steam's hourly limit [29] |
| 小美, profile author / community helper | builds a profile for an in-game dialog, shares it on Discord or Bahamut | step editor, OCR anchors, export that works at other resolutions | support burden |
| Anti-persona | wants code generation, guessing or brute force | - | unsupported by design |

### 5.2 Scope
- **MVP**: paste/file/image/clipboard-image/screen-snip import; presets, normalisation, dedupe; review table with confidence highlighting; profiles using the step types in 5.5 (except image template);
  run with pre-flight, countdown, foreground guard, F8/F9, failsafe corner, physical-input pause and mini bar; results, history skip, CSV; 3 templates; profile JSON import/export; zh-TW and en; dark and light.
- **Later**: click image template; loops and branches; drag-reordering the queue; multiple profiles in one run; scheduled runs; an optional code-feed subscription (opt-in, never bundled); template gallery; portable auto-update; Steam template.

### 5.3 Information architecture (sidebar)
序號 Codes (import, review, queue) · 設定檔 Profiles (list, step editor, templates, import/export) · 執行 Run (pre-flight, live log, current step) · 紀錄 History (all attempts, evidence, skip list, CSV).
Bottom: 設定 Settings (language, theme, hotkeys, default intervals, OCR engine and languages, failsafe, data folder) · 說明 Help (safety and ToS, troubleshooting for admin, fullscreen and DPI).
Overlays: snip/point picker (crosshair, 4x magnifier, live x/y), dry-run preview, countdown, mini run bar, toasts.

### 5.4 Key flows
**F1 First run (target under 2 min)**
1. Welcome card: what it does, plus 3 rules: only your own codes; web pages are safer; you are responsible for each game's ToS [24]. Language and theme.
2. Template gallery: 網頁兌換（通用）· 遊戲內兌換視窗（通用）· HoYoverse 網頁兌換 · 從空白開始.
3. Pick target window: list (icon, title, process, 「系統管理員」 badge) or the 「點選視窗」 crosshair. If the target is elevated and AutoPress is not, warn [20].
4. Teach the steps (wizard): 「點一下序號輸入框」 (point, stored window-relative) -> 「兌換按鈕」 (OCR finds 兌換/Redeem/確認, user confirms; fallback point) -> 「結果訊息出現在哪」 (drag a region) -> 「如何關閉結果」 (Esc or OCR 確定).
5. Dry run: numbered markers on the real window, no input sent. 6. Test with one code: run 1, show the classification next to the raw OCR text so keywords can be fixed, then save.

**F2 Import** (prototype `codes_*.png`): toolbar 貼上文字 (Ctrl+V) · 開啟檔案 (.txt/.csv/.json) · 圖片辨識 (file or drag-drop) · 剪貼簿圖片 · 框選螢幕 (Esc cancels).
OCR opens a preview: the image with detected boxes on the left, codes on the right, and ignore-regions (as in Umi-OCR [18]).
Review table: mono code, flagged characters highlighted, confidence bar only for OCR sources, status chip, editable cell with live pattern check, badges for duplicates and history. A banner summarises 需確認; filter segments; a 「略過已兌換過的序號」 switch.

**F3 Run**: 開始兌換 -> pre-flight sheet (target found, integrity OK, profile tested, N codes, interval, ETA, attended or unattended) -> 3-2-1 overlay.
The run starts from the user's own click, so Windows allows the focus change [19]. The main window collapses to the mini bar (topmost, draggable, kept away from pick points and OCR regions).
For each code: focus -> steps -> classify -> log -> wait (interval + jitter).
Interruptions: F8 pause/resume, F9 stop, failsafe corner [47], real mouse/keyboard input pauses [22][23], focus lost -> pause plus toast. On a rate-limit message: cool down, then resume or stop on the 2nd hit.

**F4 Results / History**: per-run and global tables, message text, evidence crop; 重試失敗項目, 匯出 CSV (UTF-8 with BOM for Excel), 從紀錄移除.
The history key is (profile game id, normalised code), and import skips those codes by default.

### 5.5 Step types
| Step | UI label | Parameters | Notes |
|---|---|---|---|
| focus_window | 切換到視窗 | process name, title regex, class; restore if minimised; timeout | on failure pause: 「請點一下目標視窗」 [19] |
| click_point | 點擊位置 | x/y as fractions of the client area, button, double, ±px jitter | preview marker; re-pick button |
| click_text | 點擊文字 (OCR) | text or regex, OCR language, search region, nth match, offset, min confidence | resolution independent; fallback point |
| click_image | 點擊圖片 (later) | template PNG, threshold, region, scale range | later |
| type_code | 輸入序號 | method (Unicode keys / paste), per-key delay, clear first (Ctrl+A, Del) | IME-safe default to be chosen by R1/R2 |
| type_text | 輸入文字 | template with {code} {index} {date} | e.g. `/redeem {code}` |
| key | 按鍵 / 組合鍵 | key or combo (Enter, Esc, Ctrl+V), repeat | |
| wait | 等待 | ms, jitter ±% | |
| wait_text | 等待文字出現 | text or regex, region, timeout, poll interval | e.g. wait for the dialog |
| ocr_check | 辨識結果 | region, keyword groups (section 4), unknown policy, save evidence | sets {result} |
| if_stop | 條件停止 | result in {...}, N failures in a row, rate-limited -> stop / pause / cool down N s | |

### 5.6 Safety UX (**P**, with evidence)
- Foreground guard: before each input burst check that the foreground hwnd/pid is the target, otherwise pause (pattern from [9]; risk from [15][19]).
- Failsafe: mouse in the top-left corner stops the run (as in PyAutoGUI [47]). Global hotkeys F8/F9 can be changed; do not use Esc, which games need.
- Physical input pauses the run: low-level hooks tell injected events from real ones [22][23].
- Rate limits: a per-profile interval (default 6-8 s, compare ~5 s in [7]). On rate-limit text stop retrying at once, because Steam retries reset the timer [29]. Cooldown is at least the profile value (ASF: 1 h [8]).
- Elevation: detect it and explain that UIPI drops input silently [20]. Fullscreen: black or uniform capture -> borderless hint [26].
- Dry-run overlay: transparent, click-through, numbered points and regions; also shown from the step editor (「顯示點位」).
- Honest copy: injected input is detectable [22] and macros have been penalised [24]. Prefer web pages, and the app never runs while you play. Not legal advice.
- Confirm runs over 30 codes; optional daily cap; everything stays local (no telemetry, codes never leave the PC).

### 5.7 Sharing UX (**P**)
- Export `name.autopress.json` (UTF-8) with: `schema, name, game, author, locale, target{process,title_regex}, reference{client_w,client_h,dpi}, steps[], keywords{}, interval{min_s,max_s}, preset`.
  Codes, history and screenshots are never exported.
- Resolution independence: client-relative fractions, OCR text anchors preferred, reference size recorded. If the aspect or size differs on import, the 「校正」 wizard re-picks 2 anchor points. The process is per-monitor-v2 DPI aware [25].
- Import safety: schema validation, no executable content, and a plain summary before saving (「此設定檔會：點擊 2 處、輸入序號、按 Enter」).

### 5.8 Built-in templates (MVP)
1. 網頁兌換（通用）: focus browser -> click_text field label or click_point input -> Ctrl+A, Del -> type_code -> Enter or click_text 兌換/Redeem -> wait_text -> ocr_check -> close (確定/OK or Esc) -> wait 6-8 s.
2. 遊戲內兌換視窗（通用）: focus game (dialog already open) -> click input -> type_code -> click 確認 -> ocr_check -> close popup -> wait.
3. HoYoverse 網頁兌換: template 1 + the HoYoverse preset + keyword pack from [1]. Note to the user: log in and choose server and character first [33].
   Steam is left for later because of its strict hourly limit [29] and because templates should not tick agreement checkboxes for the user.

## 6. Visual design system (tokens in `prototype.py`)
| Token | Dark | Light | Use |
|---|---|---|---|
| bg_app / bg_sidebar | #0E1014 / #12151A | #F5F6F8 / #ECEFF3 | window; sidebar and status bar |
| surface / surface_raised | #171A20 / #1E222A | #FFFFFF / #FFFFFF | cards / buttons and inputs |
| surface_hover / surface_inset | #262B34 / #101317 | #F1F3F6 / #EEF1F4 | hover / segmented track, empty art |
| overlay · nav_active · row_selected | #1C2027 · #1D2230 · #1C2638 | #FFFFFF · #DFE6F5 · #EAF0FE | menus, toasts, mini bar · active nav · opaque table selection |
| border / border_strong | #242933 / #333A46 | #E3E7EC / #CDD3DB | dividers, cards / control borders |
| text / secondary / muted | #E7E9EE / #A9B1BE / #848C9B | #14181F / #4A5361 / #646D7C | on surface: 14.4/8.1/5.15:1 dark, 17.8/7.8/5.2:1 light |
| accent / accent_fill | #6B93FF / #2F66F0 | #2F66F0 / #2F66F0 | focus, progress / primary button (white 4.9:1) |
| success / warning / error | #3DD68C / #F5B544 / #F87171 | #16A34A / #D97706 / #DC2626 | each has `_soft` (10-14 % alpha) and `_text` (5.0:1 or more on soft) |
| info / violet / orange / neutral | #5CC8FF / #A78BFA / #FB923C / #8A93A3 | #0284C7 / #7C3AED / #EA580C / #64748B | cooldown / already used / expired / pending, skipped |

Status chips: 待兌換 neutral (ring) · 兌換中 accent · 需確認 warning · 成功 success · 已使用 violet · 無效 error · 已過期 orange · 冷卻中 info · 已略過 neutral (dash).
**Type**: Microsoft JhengHei UI, falling back to Segoe UI (JhengHei UI's Latin glyphs follow Segoe UI; both are present on this PC). Codes use Consolas 14 (slashed zero, distinct 1/l/I); numbers use Segoe UI with `tnum`.
Sizes: display 22 bold · title 15 bold · body 13 · small 12 · caption 11 bold. JhengHei UI has no semibold weight, so use bold sparingly.
**Spacing** 4/8/12/16/20/24/32/40 · page padding 24x20 · card padding 16x12 · 16 between sections. **Radii** 4 keycap · 8 control · 12 card · 14 floating · pill for chips and switches.
**Sizes** control 32 · table row 42 · nav item 38 · chip 22 · keycap 20 · sidebar 220. **Elevation**: cards stay flat (border + surface step).
Floating elements get QGraphicsDropShadowEffect (blur 28, y 8, `shadow` token); the effect only shows when the parent is painted.
**Icons**: 32 original 24x24 line icons in `ICONS` (stroke 1.8, round caps), rendered with QSvgRenderer at the device pixel ratio and recoloured per theme. No third-party icon pack.
Segoe Fluent Icons is missing on this Win10 PC (Segoe MDL2 Assets exists), which is one more reason for our own SVGs.

| Component | Spec | Prototype |
|---|---|---|
| sidebar nav item | 38 px, icon 18, label 13, count pill; active = nav_active fill + 3 px accent bar | yes |
| card | surface, 1 px border, r12, padding 16x12 | yes |
| buttons: primary / secondary / ghost / icon / danger | h32 r8; primary accent_fill bold; ghost transparent; icon 32x32; disabled primary = inset + border | yes |
| toggle switch · segmented control | 34x20 pill, 14 px knob · inset track r9, segment h26 r7, selected seg_active + border | yes |
| status chip · keycap | h22 pill, dot/ring/dash + 12 px bold · h20, 2 px bottom border | yes |
| table | no grid, 42 px rows, 1 px dividers, 12 px bold muted header, custom delegates (mono code, confidence bar, chip) | yes |
| search field · combo | h32 with painted leading icon · h32 with painted chevron, `combobox-popup: 0` | yes |
| banner · empty state | soft fill + 1 px tone border, icon, text, ghost action, close · dashed art, title, hint, CTAs, keycap tip | yes |
| progress ring / bar · mini run bar | ring 40 px, 4 px round-cap stroke; bar 4 px rounded track + tone fill (confidence column) · r14 overlay + shadow, grip, ring, mono code, result chips, pause/stop + keycaps | yes |
| toast · step-list item | overlay r10, icon + text + action, 4 s · 44 px: drag handle, step icon, title + muted parameter summary, enable switch, kebab | spec only |

**Qt lessons from the prototype (checked against the rendered PNGs)**: QLineEdit's action/clear buttons are QToolButtons, so a global QToolButton rule leaks onto them (the icon was off-centre); scope it as `QLineEdit QToolButton`.
A container rule like `QFrame#X QLabel {border:none}` outranks `QLabel[role=..]` and silently removed the keycap borders. Alpha selection colours darken when Qt paints them twice, so use the opaque `row_selected`.
Delegates first draw `CE_ItemViewItem` with empty text, which keeps the QSS dividers and selection, and then paint their content. A fixed control height of 32 sits below Qt's padded sizeHint of 37 and does not clip; check text against the font height instead.

## 7. Open questions for the team
1. Typing method (Unicode keys, scan codes or clipboard paste) under an active 注音 IME, in a browser and in a game. No source found; R1/R2 should measure it.
2. OCR engine for zh-TW plus Latin codes: Windows OCR needs language packs [16]; offline Paddle/Rapid engines as in Umi-OCR [18]. Confusable rates decide how strong the review UI must be.
3. Elevated games: offer an "always run as admin" option, or only explain? 4. History store (SQLite or JSON) and its retention.
5. Final ToS and anti-cheat wording; no legal review done. 6. Whether a template may click consent checkboxes (proposal: never).

## 8. Prototype
`.venv/Scripts/python.exe docs/research/scripts/ux/prototype.py` writes `codes_dark.png`, `codes_light.png`, `codes_empty_dark.png`, `codes_empty_light.png`, `minibar_dark.png` and `minibar_light.png`.
`--theme dark --scale 1.25` gives `codes_dark_125pct.png`; `--scale 1.5` gives `codes_dark_150pct.png` and `codes_light_150pct.png`; `--live` shows the window.
It uses the windows platform + `WA_DontShowOnScreen` (never offscreen) and Fusion + QSS + QPalette generated from the tokens. The window is 1280x800 logical; all data is fake.
Checks: every PNG was viewed over 4 render-and-review rounds (fixed the search icon, stretched keycaps, heavy selection, a faint disabled button, a wide mini bar). The built-in clipping check reports 0 issues at 100/125/150 %.
The WCAG contrast report prints 16 pairs per theme, all at least 4.5:1 (lowest: light text_muted on bg_app 4.83, on_accent on accent_fill 4.91).

## 9. Sources
[1] https://raw.githubusercontent.com/seriaati/genshin.py/master/genshin/errors.py · [2] https://github.com/seriaati/hoyo-codes · [3] https://monsieur-kuma.github.io/kuma-bot/en/docs/Auto/auto_redeem
[4] https://www.chromeboard.com/extension/traveler-assistant-nhhfhlllflbgfenfiooogkiljlkbhgjc · [5] https://addons.mozilla.org/en-US/firefox/addon/genshin-star-rail-codeenter
[6] https://chromewebstore.google.com/detail/genshcode/ppgfhjllhnhnifcbbkmippmdhgogdhdm/reviews · [7] https://greasyfork.org/fi/scripts/33052-batch-register-steam-keys
[8] https://github.com/JustArchiNET/ArchiSteamFarm/wiki/Background-games-redeemer · [9] https://github.com/fenneh/mtga-code-slammer · [10] https://github.com/mavtxrx/kingshot-gift-code
[11] https://github.com/andyx0/Redeemer · [12] https://en.wikipedia.org/wiki/Macro_recorder · [13] https://techlasi.com/savvy/tinytask-exe-guide-to-windows-automation/ · [14] https://www.macrocreator.com/
[15] https://www.autohotkey.com/docs/v2/howto/SendKeys.htm · [16] https://learn.microsoft.com/en-us/windows/powertoys/text-extractor · [17] https://getsharex.com/docs/ocr · [18] https://github.com/hiroi-sora/Umi-OCR
[19] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow · [20] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
[21] https://www.autohotkey.com/docs/v2/FAQ.htm · [22] https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-kbdllhookstruct · [23] https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-msllhookstruct
[24] https://esports.ru/genshin-impact/news/v-genshin-impact-budut-vydavat-bany-i-otbirat-donatnuyu-valyutu/ (2025-11-16) · [25] https://www.autohotkey.com/docs/v2/misc/DPIScaling.htm
[26] https://help.gyazo.com/Can't%20capture%20PC%20game%20screens-6a2a77615e13056460b87886 · [27] https://forums.beamdog.com/discussion/comment/954702 (quotes Steam's invalid-code text)
[28] https://en-americas-support.nintendo.com/app/answers/detail/a_id/22429 · [29] https://steamcommunity.com/discussions/forum/1/2254560552290315498 · [30] https://steamcommunity.com/discussions/forum/1/640179350026597332
[31] https://partner.steamgames.com/doc/features/keys · [32] https://wiki.biligame.com/zzz/%E5%85%91%E6%8D%A2%E7%A0%81 · [33] https://bittopup.com/article/Genshin-63-Codes-Jan-2026-300-Primogems-Expire-in-24hrs (+ official SPA pages https://genshin.hoyoverse.com/en/gift, https://hsr.hoyoverse.com/gift)
[34] https://zenless.hoyoverse.com/redemption (official page, linked from [32]) · [35] https://www.bluestacks.com/blog/redeem-codes/wuthering-waves-redeem-codes-en.html · [36] https://www.pocketgamer.com/blue-archive/coupon-codes
[37] https://forums.maplestory.nexon.net/discussion/25/marvel-machine-101 · [38] https://axeetech.com/arknights-codes/ · [39] https://www.eneba.com/support/article/unable-to-redeem-25-character-digital-code-on-xbox
[40] https://nintendo.com/en-gb/Support/Nintendo-Switch/Error-Message-This-Code-Has-Already-Been-Used-1379025.html · [41] https://community.adobe.com/%E8%B3%AA%E5%95%8F-178/%E3%81%93%E3%81%AE%E3%82%B3%E3%83%BC%E3%83%89%E3%81%AF%E6%97%A2%E3%81%AB%E4%BD%BF%E7%94%A8%E3%81%95%E3%82%8C%E3%81%A6%E3%81%84%E3%81%BE%E3%81%99-362742
[42] https://community.adobe.com/質問-197/インストールの際にシリアル番号を入力しても-入力したシリアル番号は無効です-と出る-369285 · [43] https://bittopup.com/ko/article/NIKKE-CDK-Code-Errors-Fix-Already-UsedInvalid-2026
[44] https://bittopup.com/zh-hk/article/NIKKE-CDK-Codes-Not-Working-Fix-Already-Used-Invalid-Errors-2026 · [45] https://labs.invenglobal.com/articles/19227/how-to-fix-the-error-2103-operation-frequency-too-high-error-in-marvel-rivals
[46] https://www.gamespark.jp/article/2022/10/24/123748.html · [47] https://pyautogui.readthedocs.io/en/latest/quickstart.html
Notes: [41][42] are Adobe forum titles and [43][44] are third-party article titles; they serve as real-world wording only. [6] page shows one review. Fetched 2026-11-17; mintlify HoYoVista pages returned 410 and are not cited.
