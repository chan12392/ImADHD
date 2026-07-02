"""기존 핀 삭제 → 버튼핀 재생성. 포맷/버전 교체 시 사용.

사용: python -m scripts.repin  (cwd=ImADHD)
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    print("old msg_id:", board.msg_id)
    print("status_text:", board.status_text())
    board.repin()
    print("new msg_id:", board.msg_id)
    print("OK 버튼핀 재생성 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
