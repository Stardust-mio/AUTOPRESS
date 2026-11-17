# OWNED BY G4 - replace this stub
"""Fake redemption window for end-to-end tests and demos (a separate PyQt6 process).

    .venv/Scripts/python.exe tools/fake_redeem_app.py --title "AutoPress Fake 1234" \
        --lang zh-TW --boxes 1 --valid AAAA-1111,BBBB-2222 --rate-limit 0 \
        --popup label --popup-on always --latency-ms 0 --persist \
        --log C:/.../events.jsonl --info C:/.../info.json

Spec (SPEC section 8.4): label 請輸入兌換碼 / Enter your redeem code; 1 or 3 QLineEdits
(--boxes 3: auto-advance after 5 characters, or --groups 4,6,2 for unequal boxes); buttons
兌換 / Redeem and 取消 / Cancel; result messages 兌換成功 (valid, first time), 此序號已被使用
(valid, again), 兌換碼已過期 (codes starting with EXP), 操作過於頻繁，請稍後再試 (more than
--rate-limit submits within 10 s; 0 = off), 兌換碼無效 (otherwise) - English equivalents with
--lang en; --popup label|dialog (dialog = modal QDialog with a 確定 / OK button);
--popup-on success|always|never (which results open the dialog; the others show inline);
--latency-ms N (the result appears N ms after the submit); --persist (the label keeps the
previous result until the new one replaces it - stale-read tests for ocr_check only_new_text).
Logs every submit/result as JSON lines and writes HWND, pid and PHYSICAL rects of inputs,
buttons and result area to --info.
"""

from __future__ import annotations

import sys

__stub__ = True


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
