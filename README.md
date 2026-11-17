# AutoPress 序號自動輸入

![AutoPress](autopress/resources/icon.png)

**AutoPress** 是 Windows 10／11 上的遊戲兌換序號自動輸入工具。把手上的序號一次匯入（貼上、檔案、圖片辨識），它會照「設定檔」裡的步驟，一筆接一筆自動輸入、送出，並用文字辨識（OCR）讀出每筆的結果。通用型，不限定哪一款遊戲或哪一個兌換網頁。

- 版本：0.1.0（開發中）
- 授權：GPL-3.0（見 [LICENSE](LICENSE)；第三方元件見 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)）
- English: see [Quick start (English)](#quick-start-english) below.

> [!IMPORTANT]
> **下載後先解壓縮，再執行。** 直接在壓縮檔裡按兩下 `AutoPress.exe` 會無法啟動。請在壓縮檔上按右鍵 →「解壓縮全部」，再到解壓縮出來的 `AutoPress-<版本>` 資料夾執行 `AutoPress.exe`。

## 第一次執行：Windows 的安全提醒

AutoPress 沒有付費的程式碼簽章，第一次執行時 Windows 可能會擋下來：

1. 出現藍色視窗「**Windows 已保護您的電腦**」時，按「**其他資訊**」。
2. 確認「應用程式」是 `AutoPress.exe`，再按「**仍要執行**」。

**防毒軟體跳出警告怎麼辦？** AutoPress 會模擬鍵盤與滑鼠輸入、註冊全域快捷鍵（F8／F9）、擷取螢幕畫面來辨識文字，這些動作和某些惡意程式很像，所以少數防毒軟體可能誤判。

- AutoPress 不連網、不收集資料、關閉後不留背景程式；完整原始碼都在這個 repo 裡，可以自行檢查。
- 如果檔案被隔離：從防毒軟體的「隔離區」還原，或把 AutoPress 資料夾加入例外清單；也可以刪掉整個資料夾，重新下載壓縮檔並解壓縮。
- 只從你信任的來源取得 AutoPress 的壓縮檔。

## 下載

> [!NOTE]
> **（待定）下載方式尚未決定。** 這個 repo 目前是私人（private）repo，其他人無法從這裡下載。要怎麼把壓縮檔提供給其他人，等專案擁有者決定後再補上這一節。

## 它能做什麼

- **匯入序號**：貼上文字（Ctrl+V）、開啟檔案（.txt、.csv、.tsv、.json、.log）、圖片辨識（選檔或拖曳）、剪貼簿圖片、框選螢幕。辨識結果會先讓你確認，容易認錯的字元（例如 0／O、1／I）會標出來。
- **整理佇列**：自動去除重複、可調整順序、只跑勾選的或只跑還沒完成的；每筆序號都有狀態（待兌換、需確認、成功、已使用、無效、已過期、失敗、已略過……）。
- **設定檔**：描述「對哪個視窗、依序做什麼」：點擊位置、點擊文字（用 OCR 找按鈕）、輸入序號、按鍵、等待、等待文字出現、辨識結果。內建三個範本：網頁兌換（通用）、HoYoverse 網頁兌換、遊戲內兌換視窗（通用）；選好範本後，設定精靈會帶你點選輸入框與結果範圍。
- **自動兌換**：一筆接一筆輸入、送出、讀結果；每筆之間有間隔（預設 6–8 秒，含隨機抖動）。看到「操作過於頻繁」會冷卻或停止；連續失敗幾筆會自動停止；結果看不懂時會暫停問你。
- **一個序號分好幾格**：依分隔符號或固定字數拆段，段與段之間按 Tab 或不按。
- **紀錄**：每次嘗試都記下來（含結果畫面的截圖）；已成功或已使用的序號之後匯入會自動略過；可匯出 CSV（Excel 開中文不會亂碼）。
- **分享設定檔**：匯出成 `名稱.autopress.json`（不含序號、紀錄和截圖）。匯入別人的設定檔時，會先逐行列出它會送出的按鍵與文字，你勾選「我看得懂這些動作」才會存；匯入的設定檔一律要你自己選目標視窗。

## 安全設計

- **只輸入你自己的序號**：AutoPress 不產生、不猜測、不暴力嘗試序號。
- **前景保護**：每次按鍵、點擊前都確認最前面的視窗是目標視窗；不是就立刻暫停，不會打到別的視窗。
- **隨時可以停**：F8 暫停／繼續、F9 停止（可改鍵）；滑鼠推到螢幕左上角（多螢幕時是最外側的左上角）會緊急停止；你一動滑鼠或鍵盤，AutoPress 會在下一次輸入或點擊之前自動暫停。
- **開始前檢查**：開跑前列出檢查清單（找到目標視窗了沒、權限、設定檔測過了沒、預估時間），再倒數 3 秒。
- **資料只在你的電腦**：離線運作、不連網、沒有遙測。
- **誠實提醒**：AutoPress 只是代替你手動輸入序號，但自動輸入是偵測得到的，也有遊戲處罰過巨集。建議優先使用官方的兌換網頁；各遊戲的使用條款請自行確認（以上不是法律建議）。

## 使用說明

完整的「截圖＋說明」使用說明：[docs/user_guide.md](docs/user_guide.md)（整合完成後以正式版畫面撰寫）。

快速流程：

1. 解壓縮後執行 `AutoPress.exe`，在歡迎畫面選語言與外觀。
2. 到「**設定檔**」頁按「從範本新增」，選一個範本（兌換網頁優先選「網頁兌換」）。在「遊戲」欄填上遊戲名稱。
3. 照設定精靈的指示：選目標視窗（遊戲或兌換網頁）→ 點一下序號輸入框 → 框出結果訊息的範圍 → 選怎麼關閉結果視窗。
4. 到「**序號**」頁匯入序號，檢查標成「需確認」的序號。
5. 先按「**測試一筆**」確認結果判讀正確，再按「**開始兌換**」。執行中主視窗會縮成迷你控制列；F8 暫停、F9 停止。

## 系統需求

- Windows 10 或 Windows 11（64 位元）。不需要系統管理員權限，不需要安裝、不需要連網。
- 解壓縮後約 200 MB（估計值）。
- 遊戲若以系統管理員身分執行，Windows 會擋下一般程式的模擬輸入；這時開始前的檢查清單會提醒你，按「以系統管理員身分重新啟動」即可。
- 獨佔全螢幕的遊戲畫面截不到（會是全黑）；請把遊戲改成「無邊框視窗」或視窗模式。

## 資料放在哪裡

設定、設定檔、序號佇列、紀錄和結果截圖都存在 `%APPDATA%\AutoPress`（在檔案總管的網址列輸入 `%APPDATA%\AutoPress` 就能打開；程式的「設定 → 資料」也有「開啟資料夾」按鈕）。

**可攜模式**：在 `AutoPress.exe` 旁邊新增一個空白文字檔，檔名改成 `portable.txt`，之後所有資料都會存在 AutoPress 資料夾裡的 `data` 子資料夾（適合放在隨身碟）。發佈的壓縮檔裡沒有這個檔案，要用時自己建立。

## 常見問題

- **按了開始卻沒有輸入任何字**：目標程式可能以系統管理員身分執行（開始前的檢查清單會提醒），或遊戲只認實體按鍵：在設定檔的「輸入序號」步驟改用「遊戲模式（按鍵碼）」或「貼上（剪貼簿）」，再用「測試一筆」確認。
- **輸入的字被注音輸入法改掉**：預設的「模擬鍵入」不受注音影響；「遊戲模式」會先暫時關閉目標視窗的輸入法。仍有問題時改用「貼上」。
- **找不到按鈕文字**：確認兌換視窗已開啟；在設定檔裡調整要找的文字（例如 `兌換|Redeem`）或設定搜尋範圍。
- **畫面截圖全黑**：遊戲在獨佔全螢幕模式；改成無邊框視窗。
- **以系統管理員身分執行 AutoPress 時無法拖放檔案**：這是 Windows 的限制，請改用「開啟檔案」。
- 程式內的「說明」頁有更完整的疑難排解。

## 從原始碼執行與打包

需要 python.org 的 Python 3.12.10（64 位元）。在專案資料夾裡：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py                       # 從原始碼執行
.venv\Scripts\python.exe -m pytest -q                  # 測試
.venv\Scripts\python.exe main.py --selftest report.json   # 自我檢測（寫出 JSON 報告）
```

打包成發佈用的壓縮檔（one-folder 版本）：

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3 pyinstaller-hooks-contrib==2026.10
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` 會用 `autopress.spec` 重新建置 `dist\AutoPress\AutoPress.exe`，執行 `AutoPress.exe --selftest`（也從一個路徑含中文的資料夾再跑一次），再把程式、說明與授權檔打包成 `dist\AutoPress-<版本>-win64.zip`。圖示由 `tools\make_icon.py` 產生。

專案結構與每個模組的規格見 [SPEC.md](SPEC.md)。

## 授權

AutoPress 以 GNU General Public License 第 3 版（GPL-3.0）授權，全文見 [LICENSE](LICENSE)。發佈的程式內含 PyQt6（GPL-3.0）、Qt 6（LGPL-3.0）、RapidOCR 與 PP-OCRv6 模型（Apache-2.0）、ONNX Runtime（MIT）、OpenCV（Apache-2.0）等第三方元件，各自的授權與全文見 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 與 [licenses/](licenses/)。

---

## Quick start (English)

AutoPress enters game redeem codes for you on Windows 10/11: import your codes (paste, file or image OCR), pick or build a profile that says which window to use and which steps to take, and AutoPress types and submits the codes one by one, reads each result with OCR and keeps a history. It works offline, needs no admin rights and never generates or guesses codes. The full user guide ([docs/user_guide.md](docs/user_guide.md)) is in Traditional Chinese; the app itself also runs in English (Settings → Language).

1. **Unzip first.** Right-click the zip → "Extract All", then run `AutoPress.exe` inside the extracted `AutoPress-<version>` folder. Starting it from inside the zip does not work.
2. **"Windows protected your PC"** (the app is not code-signed): click **More info**, check that the app is `AutoPress.exe`, then click **Run anyway**. If your antivirus quarantines a file (AutoPress simulates keyboard and mouse input, registers the F8/F9 hotkeys and captures the screen for OCR), restore it from quarantine or download and unzip the package again.
3. On the **Profiles** page click "New from template" and pick one: *Web redeem page (generic)*, *HoYoverse web redeem* or *In-game redeem dialog (generic)*. Enter the game name, then follow the setup wizard: pick the target window, click the code input box, drag over the area where the result message appears, and choose how the result popup is closed.
4. On the **Codes** page import your codes and check the ones marked *Needs review*.
5. Click **Test one** (Codes or Run page) to check that the result is read correctly, then **Start**. During a run the main window shrinks to a mini bar: **F8** pauses / resumes, **F9** stops, and moving the mouse into the outer top-left corner of the desktop is an emergency stop. If you move the mouse or type, the run pauses before AutoPress types or clicks again.

Your data stays in `%APPDATA%\AutoPress` (or in a `data` folder next to the exe when you create an empty `portable.txt` there). Downloads: not decided yet (see 「下載」 above). Licence: GPL-3.0; third-party notices in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
