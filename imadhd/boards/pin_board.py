"""텔레그램 공지(Pin) 보드: 슬롯 상태 시각화 + 자동 갱신.

출력 예: 1️⃣⭕  2️⃣❌  3️⃣📝  4️⃣❌  5️⃣❌  6️⃣❌
상태: ⭕ 연결(idle) / ❌ 종료(빈 슬롯) / 📝 작업중(busy)
변경 시에만 editMessageText 로 갱신(API 절약).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..commands.inject_command import EMOJI_TO_NUM

if TYPE_CHECKING:
    from ..telegram_api.client import TelegramClient
    from ..core.registry import Registry

NUM_EMOJI = {v: k for k, v in EMOJI_TO_NUM.items()}


class PinBoard:
    def __init__(self, tg: "TelegramClient", reg: "Registry", chat_id: str,
                 data_dir: Path, max_slots: int):
        self.tg = tg
        self.reg = reg
        self.chat = chat_id
        self.max_slots = max_slots
        self.id_file = Path(data_dir) / "pin_message_id.txt"
        self.msg_id = self._load_id()
        # 시작 시 현재 status_text 로 초기화 → 첫 refresh_if_changed 가
        # 핀 실제와 동일하면 edit 안 함 ("not modified" 400 회피).
        self._last_text: str | None = self.status_text() if self.msg_id else None

    def _load_id(self) -> int | None:
        try:
            return int(self.id_file.read_text(encoding="utf-8").strip() or "0") or None
        except Exception:
            return None

    def _save_id(self, mid: int) -> None:
        self.id_file.parent.mkdir(parents=True, exist_ok=True)
        self.id_file.write_text(str(mid), encoding="utf-8")

    def status_text(self) -> str:
        act = {i.number: i for i in self.reg.active()}
        parts = []
        for n in range(1, self.max_slots + 1):
            info = act.get(n)
            emoji = NUM_EMOJI.get(n, f"[{n}]")
            if not info:
                mark = "❌"
            elif info.status == "busy":
                mark = "📝"
            else:
                mark = "⭕"
            parts.append(f"{emoji}{mark}")
        return "  ".join(parts)

    def create(self) -> None:
        if not self.chat:
            return
        text = self.status_text()
        mid = self.tg.send(self.chat, text)
        if mid:
            self.msg_id = mid
            self._last_text = text
            self._save_id(mid)
            self.tg.pin_chat_message(self.chat, mid)

    def refresh_if_changed(self) -> None:
        if not self.msg_id:
            return
        text = self.status_text()
        if text != self._last_text:
            self.tg.edit_message_text(self.chat, self.msg_id, text)
            self._last_text = text
