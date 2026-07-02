"""텔레그램 상태 보드: ReplyKeyboard(입력창 아래 영구 버튼).

출력(버튼): 1️⃣.⭕ 2️⃣.❌ 3️⃣.📝 4️⃣.❌ 5️⃣.❌ 6️⃣.❌  (3열 그리드)
상태: ⏳ 선택대기(pending) / 📝 작업중(busy) / ⭕ 연결(idle) / ❌ 종료(빈 슬롯)

ReplyKeyboard 특징:
  - 입력창 아래 상시(스크롤에 안 묻힘). 핀 아님.
  - 버튼 클릭 = 버튼 텍스트("1️⃣⭕")가 메시지로 전송(callback 아님).
  - router가 선두 번호이모지 파싱 → 본문(상태마크만)이면 상태 회신,
    본문 있으면 주입.
  - 상태 변 시 editMessageReplyMarkup 로 키보드만 갱신(text 고정, API 절약).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..commands.inject_command import EMOJI_TO_NUM

if TYPE_CHECKING:
    from ..telegram_api.client import TelegramClient
    from ..core.registry import Registry

NUM_EMOJI = {v: k for k, v in EMOJI_TO_NUM.items()}
COLS = 3  # 버튼 열 수(행은 max_slots/COLS 올림)


class PinBoard:
    def __init__(self, tg: "TelegramClient", reg: "Registry", chat_id: str,
                 data_dir: Path, max_slots: int):
        self.tg = tg
        self.reg = reg
        self.chat = chat_id
        self.max_slots = max_slots
        self.id_file = Path(data_dir) / "pin_message_id.txt"
        self.msg_id = self._load_id()
        # 저장된 핀 msg_id 가 있어도 _last_key=None → 첫 refresh_if_changed 가
        # 무조건 edit 시도. router 재시작 시 핀 메시지가 옛날 상태로 고정되는
        # 버그 방지(registry active 는 안정이라 key 같으면 edit 스킵 → 핀 방치).
        # edit_message_text 가 400 "not modified" 를 잡으므로 불필요 edit도 안전.
        self._last_key: tuple | None = None
        # 선택대기(pending) 번호: 해당 슬롯 마크 ⏳ 로 표시. None=대기 없음.
        self.pending_num: int | None = None

    def _load_id(self) -> int | None:
        try:
            return int(self.id_file.read_text(encoding="utf-8").strip() or "0") or None
        except Exception:
            return None

    def _save_id(self, mid: int) -> None:
        self.id_file.parent.mkdir(parents=True, exist_ok=True)
        self.id_file.write_text(str(mid), encoding="utf-8")

    def _mark_for(self, info, num: int) -> str:
        """슬롯 마크 우선순위: ⏳ 선택대기 > 📝 작업중 > ⭕ 연결 > ❌ 종료."""
        if self.pending_num == num:
            return "⏳"
        if not info:
            return "❌"
        if info.status == "busy":
            return "📝"
        return "⭕"

    def status_text(self) -> str:
        act = {i.number: i for i in self.reg.active()}
        parts = []
        for n in range(1, self.max_slots + 1):
            emoji = NUM_EMOJI.get(n, f"[{n}]")
            parts.append(f"{emoji}.{self._mark_for(act.get(n), n)}")
        return "  ".join(parts)

    def status_markup(self) -> dict:
        """ReplyKeyboard: COLS열 그리드. 버튼=번호+상태. 클릭→텍스트 전송."""
        act = {i.number: i for i in self.reg.active()}
        rows, row = [], []
        for n in range(1, self.max_slots + 1):
            emoji = NUM_EMOJI.get(n, f"{n}")
            row.append({"text": f"{emoji}.{self._mark_for(act.get(n), n)}"})
            if len(row) >= COLS:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return {"keyboard": rows, "resize_keyboard": True}

    def _key(self, text: str, markup: dict) -> tuple:
        return (text, json.dumps(markup, ensure_ascii=False, sort_keys=True))

    def create(self) -> None:
        if not self.chat:
            return
        text = self.status_text()
        markup = self.status_markup()
        mid = self.tg.send(self.chat, text, reply_markup=markup)
        if mid:
            self.msg_id = mid
            self._last_key = self._key(text, markup)
            self._save_id(mid)
            self.tg.pin_chat_message(self.chat, mid)   # 상단 핀 고정

    def refresh_if_changed(self, pending_num: int | None = None) -> None:
        if not self.msg_id:
            return
        self.pending_num = pending_num   # 선택대기 번호 반영(⏳)
        text = self.status_text()
        markup = self.status_markup()
        key = self._key(text, markup)
        if key != self._last_key:
            # 핀 메시지 본문(text) + 키보드(markup) 둘 다 실시간 갱신
            self.tg.edit_message_text(self.chat, self.msg_id, text, reply_markup=markup)
            self._last_key = key

    def repin(self) -> None:
        """기존 보드 메시지 삭제 후 새로 생성(포맷/버전 변경 시 교체용)."""
        if self.msg_id:
            try:
                self.tg.delete_message(self.chat, self.msg_id)
            except Exception:
                pass
        self.msg_id = None
        self._last_key = None
        self.create()
