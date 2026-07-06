"""슬롯별 작업진행 카운터 보드.

router가 1초마다 reg.active() 를 폴링 → busy 슬롯은 카운터 메시지를
send/edit 하고, idle 로 전환되면 delete. 완료 결과(reply)는 reply_hook 이
별도 DM 으로 전송하므로 여기선 표기하지 않는다(대표님 지시 2026-07-07).

상태:
  status="busy"  -> 🟡 N번 작업중 (Xs)  생성 또는 edit(초수 갱신)
  status="idle"  -> 진행 메시지 delete

무상태 훅(busy_hook/reply_hook)이 status 만 토글하고, 장기실행 router
스레드가 이 보드로 표현을 담당한다(Windows/Linux 공통 — OS 무관).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


def _slot_label(info) -> str:
    """1번 / 1번(이름) — label 있으면 괄호 표기."""
    n = info.number
    lab = getattr(info, "label", "") or ""
    return f"{n}번({lab})" if lab else f"{n}번"


class ProgressBoard:
    """슬롯별 진행 카운터 메시지 관리. router 스레드가 1초 간격 sync() 호출."""

    def __init__(self, tg, chat_id):
        self.tg = tg
        self.chat_id = str(chat_id) if chat_id is not None else ""
        self.msgs: dict[int, dict] = {}  # {slot: {"msg_id": int, "start": float}}

    def sync(self, sessions) -> None:
        """sessions = reg.active() 결과(SessionInfo 리스트).

        busy 슬롯은 카운터 생성/갱신, busy 에서 벗어난 슬롯은 delete.
        """
        if not self.chat_id:
            return
        busy_nums = set()
        for s in sessions:
            if getattr(s, "status", "") == "busy":
                busy_nums.add(s.number)
                self._ensure(s)
        for num in list(self.msgs.keys()):
            if num not in busy_nums:
                self._delete(num)

    def _ensure(self, info) -> None:
        num = info.number
        entry = self.msgs.get(num)
        try:
            if entry is None:
                mid = self.tg.send(self.chat_id, f"🟡 {_slot_label(info)} 작업중 (1s)")[0]
                self.msgs[num] = {"msg_id": mid, "start": time.time()}
            else:
                elapsed = max(1, int(time.time() - entry["start"]))
                self.tg.edit_message_text(
                    self.chat_id, entry["msg_id"],
                    f"🟡 {_slot_label(info)} 작업중 ({elapsed}s)")
        except Exception as e:
            # 429/edit 충돌 등은 다음 틱에 재시도. 로그는 debug 만.
            log.debug("progress ensure slot=%s err=%s", num, e)

    def _delete(self, num: int) -> None:
        entry = self.msgs.pop(num, None)
        if not entry:
            return
        try:
            self.tg.delete_message(self.chat_id, entry["msg_id"])
        except Exception as e:
            log.debug("progress delete slot=%s err=%s", num, e)

    def clear(self) -> None:
        """router 종료 시 잔여 카운터 정리."""
        for num in list(self.msgs.keys()):
            self._delete(num)
