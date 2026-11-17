# OWNED BY G5
"""Help page content (SPEC 6.4.6) as data: zh-TW first, English second (``T`` pairs, resolved
when the page is built). Block kinds: ("p", T) paragraph, ("list", [T, ...]) bullets,
("item", T title, [blocks]) a titled troubleshooting entry, ("hotkeys",) the configured run
hotkeys, ("failsafe",) the monitor drawing with the corner that counts. An optional "toc" pair is the
shorter title in the page's table of contents.
"""

from __future__ import annotations

from typing import Any

from ..i18n import T

Block = tuple[Any, ...]

SECTIONS: list[dict[str, Any]] = [
    {
        "id": "about",
        "icon": "logo",
        "title": T("這是什麼", "What AutoPress is"),
        "blocks": [
            ("p", T("AutoPress 會照你設定的步驟，把一批遊戲序號一筆接一筆自動輸入、送出，並記下每筆結果。"
                    "它只是代替你手動輸入序號，不會修改遊戲。",
                    "AutoPress types a batch of game redeem codes for you, one after another, following the steps "
                    "you set up, and records every result. It only replaces typing the codes by hand; it never "
                    "modifies a game.")),
            ("list", [
                T("序號：貼上文字、開啟檔案、辨識圖片或框選螢幕，把序號加入佇列。",
                  "Codes: paste text, open a file, read an image or snip the screen to queue codes."),
                T("設定檔：記錄要對哪個視窗、依序點哪裡、輸入、怎麼判讀結果；可從範本建立。",
                  "Profiles: which window, where to click, how to type and how to read the result; start from a "
                  "template."),
                T("執行：開始前先檢查清單並倒數；執行中可暫停、繼續、停止。",
                  "Run: a checklist and a countdown come first; pause, resume or stop at any time."),
                T("紀錄：每筆的結果、訊息與證據截圖；已兌換過的序號之後會自動略過。",
                  "History: every result with its message and evidence screenshot; redeemed codes are skipped later."),
            ]),
        ],
    },
    {
        "id": "safety",
        "icon": "shield",
        "title": T("安全守則", "Safety rules"),
        "blocks": [
            ("list", [
                T("只輸入你自己的序號。AutoPress 不會產生、猜測或暴力嘗試序號，也不會自動試 O／0、I／1 的變化。",
                  "Enter only your own codes. AutoPress never generates, guesses or brute-forces codes and never "
                  "tries O/0 or I/1 variants by itself."),
                T("官方兌換網頁比較安全：輸入格固定、結果清楚，也不會和遊戲操作混在一起。",
                  "Official redeem web pages are safer: fixed input boxes, clear results, and no mix-up with "
                  "gameplay."),
                T("只匯入你信任的人分享的設定檔。設定檔就是一串按鍵與點擊，匯入前請看清楚畫面上列出的每個動作。",
                  "Import profiles only from people you trust. A profile is a list of keystrokes and clicks; read "
                  "every listed action before importing."),
                T("在聊天框用指令兌換（例如 /redeem）時，指令打錯會把序號直接公開發到聊天頻道。",
                  "Redeeming with a chat command (such as /redeem) posts the code publicly when the command is "
                  "wrong."),
                T("模擬輸入是偵測得到的，有些遊戲禁止巨集或自動化工具；是否使用由你自己判斷並負責。",
                  "Simulated input can be detected and some games forbid macros or automation; whether you use it is "
                  "your decision and your responsibility."),
                T("AutoPress 不會在你玩遊戲時偷偷執行：每次執行都要你按「開始兌換」並倒數，你一動滑鼠或鍵盤就會暫停。",
                  "AutoPress never runs while you play: every run starts from your click and a countdown, and moving "
                  "the mouse or typing pauses it."),
                T("以上不是法律建議；各遊戲的服務條款請自行確認。",
                  "This is not legal advice; check each game's terms of service yourself."),
            ]),
        ],
    },
    {
        "id": "troubleshooting",
        "icon": "help",
        "title": T("疑難排解", "Troubleshooting"),
        "blocks": [
            ("item", T("遊戲以系統管理員身分執行", "The game runs as administrator"), [
                ("p", T("Windows 會無聲擋掉一般權限程式對系統管理員程式的模擬輸入：看起來在打字，遊戲卻什麼都沒收到。"
                        "開始前的檢查清單會提醒你，並提供「以系統管理員身分重新啟動」按鈕。",
                        "Windows silently drops simulated input from normal programs into programs that run as "
                        "administrator: it looks like typing, but the game receives nothing. The pre-run checklist "
                        "warns you and offers a \"Restart as administrator\" button.")),
                ("p", T("以系統管理員身分執行時，無法從檔案總管把檔案拖曳進來，請改用「開啟檔案」。"
                        "如果你的帳戶沒有系統管理員權限，請改用遊戲的網頁兌換。",
                        "While AutoPress runs as administrator, files cannot be dragged in from Explorer; use Open "
                        "file. If your account cannot elevate, use the game's web redeem page instead.")),
            ]),
            ("item", T("全螢幕時擷取到的畫面全黑", "Captures are black in fullscreen"), [
                ("p", T("獨佔全螢幕的遊戲或鎖定的螢幕會讓擷取變成全黑或單色，文字辨識就讀不到東西。"
                        "請把遊戲改成「無邊框視窗」或視窗模式後再試；執行中偵測到全黑會自動暫停。",
                        "Exclusive-fullscreen games and a locked screen make captures black or uniform, so OCR reads "
                        "nothing. Switch the game to borderless or windowed mode; a run pauses when it sees a black "
                        "capture.")),
            ]),
            ("item", T("縮放比例與多螢幕", "Scaling and several screens"), [
                ("p", T("點擊位置是相對於目標視窗記錄的，視窗搬到別的螢幕仍然有效。若視窗大小或 Windows 縮放比例"
                        "（例如 100% 改成 125%）和錄製時不同，檢查清單會提醒；請先按「預覽點位」確認，必要時用"
                        "「重新對準」重新點選每個位置。",
                        "Positions are stored relative to the target window, so moving it to another screen is fine. "
                        "If the window size or the Windows scaling (e.g. 100% to 125%) differs from when you recorded "
                        "them, the checklist warns you: use Preview positions, and Re-align to pick every position "
                        "again when needed.")),
            ]),
            ("item", T("注音輸入法把序號改掉了", "The Chinese IME changes the code"), [
                ("p", T("在「輸入序號」步驟改用「模擬鍵入」或「貼上」，這兩種方式不受注音輸入法和 Caps Lock 影響；"
                        "「遊戲模式（按鍵碼）」會暫時關閉目標視窗的輸入法。也可以先把輸入法切到英文。",
                        "In the 'Type code' step use simulated typing or paste: neither is affected by the IME or Caps "
                        "Lock. Game mode (key codes) turns the target's IME off while typing. You can also switch "
                        "the IME to English first.")),
            ]),
            ("item", T("找不到按鈕上的文字", "The button text is not found"), [
                ("p", T("確認兌換視窗已經開啟，並在設定檔裡檢查要找的文字是否和畫面一模一樣（可用「兌換|Redeem」"
                        "列出幾種寫法），或把搜尋範圍框小一點。按「測試此步驟」可以看到實際讀到的文字。",
                        "Make sure the redeem window is open and check that the text matches the screen exactly "
                        "(list alternatives like \"兌換|Redeem\"), or draw a smaller search region. Test this step "
                        "to see the text that was actually read.")),
            ]),
            ("item", T("「Windows 已保護您的電腦」", "\"Windows protected your PC\""), [
                ("p", T("這是 SmartScreen 對沒有付費簽章的新程式的提醒。確認檔案來自你信任的下載來源後，"
                        "按「其他資訊」→「仍要執行」。",
                        "SmartScreen shows this for new programs without a paid signature. If the file comes from a "
                        "source you trust, click More info, then Run anyway.")),
            ]),
            ("item", T("防毒軟體誤判", "Antivirus false positives"), [
                ("p", T("AutoPress 會模擬鍵盤與滑鼠、讀取螢幕畫面並註冊快捷鍵，這些也是惡意程式常做的事，"
                        "所以部分防毒軟體可能誤判。若檔案被隔離，請從防毒軟體的隔離區還原並加入例外，"
                        "或重新下載完整的壓縮檔並解壓縮後再執行。",
                        "AutoPress simulates keyboard and mouse input, reads the screen and registers hotkeys - things "
                        "malware does too - so some antivirus programs may flag it. If files were quarantined, restore "
                        "them and add an exception, or download and unzip the full package again.")),
            ]),
        ],
    },
    {
        "id": "hotkeys",
        "icon": "keyboard",
        "title": T("快捷鍵與緊急停止", "Hotkeys and emergency stop"),
        "toc": T("快捷鍵與緊急停止", "Hotkeys & stop"),
        "blocks": [
            ("hotkeys",),
            ("p", T("快捷鍵只在執行期間與「真的執行」的步驟測試時註冊，平常不會佔用這些按鍵；可在「設定」更換。",
                    "The hotkeys are registered only during runs and step tests with 'Run for real'; change them "
                    "in Settings.")),
            ("failsafe",),
            ("p", T("會鎖住滑鼠游標的遊戲（例如第一人稱射擊遊戲）沒辦法把滑鼠推到角落，請改按停止快捷鍵。",
                    "Games that lock the cursor (such as first-person shooters) cannot reach the corner: use the stop "
                    "hotkey instead.")),
        ],
    },
    {
        "id": "privacy",
        "icon": "lock",
        "title": T("隱私", "Privacy"),
        "blocks": [
            ("list", [
                T("AutoPress 離線運作：不連網、不檢查更新、沒有遙測。序號、紀錄與截圖只存在這台電腦的資料資料夾。",
                  "AutoPress works offline: no network, no update checks, no telemetry. Codes, history and "
                  "screenshots stay in the data folder on this PC."),
                T("結果截圖可能拍到你的帳號或角色名稱；分享截圖前請先確認，或在「設定」關閉截圖。",
                  "Result screenshots may show your account or character name; check before sharing them, or turn "
                  "screenshots off in Settings."),
                T("匯出的設定檔不含序號、紀錄與截圖，視窗標題也只保留你確認過的關鍵字。",
                  "Exported profiles contain no codes, history or screenshots, and only a window-title keyword you "
                  "confirmed."),
            ]),
        ],
    },
]
