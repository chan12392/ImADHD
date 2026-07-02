"""수동 핀 생성 스크립트: /공지 와 동일 경로(PinBoard.create) 직접 호출.

사용: python -m scripts.pin_now  (cwd=ImADHD)
"""
from __future__ import annotations

import sys
from pathlib import Path

# 패키지 루트 보정 (스크립트 디렉토리 = ImADHD)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from imadhd.config import Settings
from imadhd.core.registry import JSONFileRegistry
from imadhd.boards.pin_board import PinBoard
from imadhd.telegram_api.client import TelegramClient


def main() -> int:
    s = Settings.load()
    if not s.allowed_chat_id:
        print("ERR: TELEGRAM_ALLOWED_CHAT_ID 없음 — .env 확인")
        return 1
    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)
    board = PinBoard(tg, reg, s.allowed_chat_id, s.data_dir, s.max_slots)
    text = board.status_text()
    print("status_text:", text)
    print("before msg_id:", board.msg_id)
    board.create()
    print("after  msg_id:", board.msg_id)
    print("OK 핀 생성 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
