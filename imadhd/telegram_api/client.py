"""텔레그램 Bot API 최소 래퍼. 의존성 0 (urllib).

- getUpdates(long_poll) + offset 영구 저장
- sendMessage
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


class TelegramClient:
    def __init__(self, token: str, offset_path: Path, allowed_chat_id: str | None = None):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.offset_path = offset_path
        self.allowed_chat_id = allowed_chat_id

    # TODO
    def get_updates(self, timeout: int = 30) -> list[dict]:
        raise NotImplementedError("implemented in plan step")

    def send(self, chat_id: str, text: str) -> None:
        raise NotImplementedError("implemented in plan step")

    # offset 영구 저장
    def _load_offset(self) -> int:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(offset), encoding="utf-8")
