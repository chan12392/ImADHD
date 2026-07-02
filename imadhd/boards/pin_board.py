"""텔레그램 상태 보드: 상단 핀(본문) + 입력창 아래 버튼(ReplyKeyboard).

★ 본문·버튼 분리 (2026-07-03): reply_markup(ReplyKeyboard) 포함 메시지는
  editMessageText 로 edit 불가("can't be edited" 400, Telegram 제약).
  → 상태 텍스트(markup 없음) 메시지 + 버튼(ReplyKeyboard) 메시지 분리.

구성:
  1. status_msg (상단 핀 고정): 본문 = 상태 마크. markup 없음 → editMessageText 실시간 갱신.
  2. keyboard_msg (ReplyKeyboard): 번호만 버튼(1️⃣..6️⃣, 상태마크 없음) → 고정. edit 불필요.

마크(본문): ⏳ 선택대기(pending) / 📝 작업중(busy) / ⭕ 연결(idle) / ❌ 종료(빈 슬롯)
버튼 클릭 = 번호이모지 메시지 전송 → router 가 선두 번호 파싱 → 본문 없으면 선택대기 등록.
"""
from __future__ import annotations

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
        self.data_dir = Path(data_dir)
        self.status_id_file = self.data_dir / "pin_message_id.txt"        # 본문(=구 핀 id)
        self.keyboard_id_file = self.data_dir / "keyboard_message_id.txt"
        self.status_id = self._load_id(self.status_id_file)
        self.keyboard_id = self._load_id(self.keyboard_id_file)
        # _last_text=None → 첫 refresh 무조건 edit(옛날 상태 동기화).
        self._last_text: str | None = None
        # 선택대기(pending) 번호: 해당 슬롯 마크 ⏳ 로 표시. None=대기 없음.
        self.pending_num: int | None = None

    def _load_id(self, f: Path) -> int | None:
        try:
            return int(f.read_text(encoding="utf-8").strip() or "0") or None
        except Exception:
            return None

    def _save_id(self, f: Path, mid: int) -> None:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(mid), encoding="utf-8")

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

    def keyboard_markup(self) -> dict:
        """ReplyKeyboard: 번호만 버튼(상태마크 없음 → 고정). 클릭=번호 메시지 전송."""
        rows, row = [], []
        for n in range(1, self.max_slots + 1):
            emoji = NUM_EMOJI.get(n, f"{n}")
            row.append({"text": emoji})
            if len(row) >= COLS:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return {"keyboard": rows, "resize_keyboard": True}

    def create(self) -> None:
        """본문(상태, markup 없음→edit 가능) + 버튼(ReplyKeyboard) 메시지 생성."""
        if not self.chat:
            return
        # 1) 상태 본문 (markup 없음 → editMessageText 갱신 가능)
        sid = self.tg.send(self.chat, self.status_text())
        if sid:
            self.status_id = sid
            self._last_text = self.status_text()
            self._save_id(self.status_id_file, sid)
            self.tg.pin_chat_message(self.chat, sid)
        # 2) 버튼 (ReplyKeyboard, 번호만 고정)
        kid = self.tg.send(self.chat, "터미널 선택", reply_markup=self.keyboard_markup())
        if kid:
            self.keyboard_id = kid
            self._save_id(self.keyboard_id_file, kid)

    def refresh_if_changed(self, pending_num: int | None = None) -> None:
        if not self.status_id:
            return
        self.pending_num = pending_num   # 선택대기 번호 반영(⏳)
        text = self.status_text()
        if text != self._last_text:
            # 본문만 editMessageText(markup 없음 → edit 가능). 활성 키보드는 유지.
            try:
                self.tg.edit_message_text(self.chat, self.status_id, text)
                self._last_text = text
            except Exception:
                self.repin()   # 본문 무효(삭제) → 전체 재생성

    def repin(self) -> None:
        """기존 본문+버튼 메시지 삭제 후 새로 생성(포맷 변경/무효 시)."""
        for mid in (self.status_id, self.keyboard_id):
            if mid:
                try:
                    self.tg.delete_message(self.chat, mid)
                except Exception:
                    pass
        self.status_id = None
        self.keyboard_id = None
        self._last_text = None
        self.create()
