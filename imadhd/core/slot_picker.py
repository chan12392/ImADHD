"""번호 필요 명령(/close /stop /use /new) 의 인라인 slot 선택 팝업.

ReplyKeyboard 기능 버튼("/close") 탭 시 인자가 없으면 → 활성 슬롯 목록을
인라인 키보드로 송신. 사용자가 번호 버튼 탭 → callback_query "s:<action>:<num>"
→ router 가 가상 Message("/close 3") 만들어 해당 Command.handle() 재진입.

ask_manager/perm_manager 와 다른 점: 영속 기록·폴링 없음. slot 선택은 즉시
실행(동기)이라 저장소 불필요. callback_data 만으로 라우터가 재진입.

흐름:
  1. 명령 handle() 인자 없음 → send_picker() 호출.
  2. send_picker: 활성 0 → 안내 답장(None). 1 → num 반환(호출자 즉시실행).
     2+ → 인라인 키보드 송신(None, 사용자 탭 대기).
  3. 활성 1 즉시실행 → rerun_with_slot(cmd, msg, ctx, action, num) 가
     가상 Message 로 cmd.handle 재진입(parts[1] 있음 = 정상 경로, 순환 아님).
  4. 2+ 팝업 → 사용자 탭 → router._handle_callback "s:" 분기 →
     rerun_with_slot 재진입 동일.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..commands.base import Command, CommandContext, Message
    from ..core.registry import Registry
    from ..telegram_api.client import TelegramClient

# action → 팝업 본문 라벨·명령 트리거 매핑.
ACTIONS = {
    "close": ("✖️ 닫을 슬롯 선택",        "close"),
    "stop":  ("⏹️ 중단할 슬롯 선택",      "stop"),
    "use":   ("🎯 고정할 슬롯 선택",      "use"),
    "new":   ("🆕 새 대화 슬롯 선택",     "new"),
}
COLS = 3   # 인라인 키보드 열 수


def build_slot_keyboard(nums_with_marks, action: str) -> list[list[dict]]:
    """활성 슬롯 → 인라인 키보드. nums_with_marks = [(num, mark_str), ...].

    callback_data = "s:<action>:<num>" (64바이트 이내 — action 짧음 + 1자리 num).
    버튼 텍스트 = "1️⃣ 🎯" 식 (번호 + 상태마크).
    """
    rows: list[list[dict]] = []
    row: list[dict] = []
    # 번호 이모지 1-9 (inject_command EMOJI_TO_NUM 와 동일 세트).
    _NUM_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
                  6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣"}
    for num, mark in nums_with_marks:
        emoji = _NUM_EMOJI.get(num, str(num))
        text = f"{emoji} {mark}".strip()
        row.append({"text": text, "callback_data": f"s:{action}:{num}"})
        if len(row) >= COLS:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # use 팝업 마지막: 고정해제 버튼(대표님 2026-07-07). 단독 행.
    # callback s:use:off → router 가상 /use 0 → use_command 해제 분기("0" in off set).
    if action == "use":
        rows.append([{"text": "🔓 고정 해제", "callback_data": "s:use:off"}])
    return rows


def parse_callback(callback_data: str) -> tuple[str, int] | None:
    """callback_data = "s:<action>:<num>" → (action, num). 불일치 → None.

    action ∈ ACTIONS 키. num 양의 정수. 그 외(잘못된 형식·action·num) → None.
    """
    if not callback_data or not callback_data.startswith("s:"):
        return None
    parts = callback_data.split(":")
    if len(parts) != 3:
        return None
    action = parts[1]
    if action not in ACTIONS:
        return None
    # use 팝업 "고정 해제" 버튼: s:use:off → (use, 0). rerun_with_slot 이 /use 0 가상
    # 메시지 → use_command 해제 분기("0" in off set). use 에만 허용.
    if parts[2] == "off":
        return (action, 0) if action == "use" else None
    try:
        num = int(parts[2])
    except ValueError:
        return None
    if num < 1:
        return None
    return action, num


def _marks_for(reg, sticky_num: int | None) -> list[tuple[int, str]]:
    """활성 슬롯 (num, mark) 목록. 우선순위: 🎯 고정 > 📝 작업중 > ⭕ 연결."""
    out = []
    for info in reg.active():
        n = info.number
        if sticky_num == n:
            mark = "🎯"
        elif getattr(info, "status", None) == "busy":
            mark = "📝"
        else:
            mark = "⭕"
        out.append((n, mark))
    out.sort(key=lambda x: x[0])
    return out


def send_picker(tg: "TelegramClient", chat: str, action: str, reg: "Registry",
                sticky_num: int | None) -> int | None:
    """action 의 slot 선택 팝업.

    반환:
      None — 활성 0(안내 답장 송신) 또는 2+(팝업 송신, 사용자 탭 대기).
      int  — 활성 1개일 때 그 슬롯 번호. 호출자가 rerun_with_slot 즉시실행.
    """
    if action not in ACTIONS:
        return None
    marks = _marks_for(reg, sticky_num)
    if not marks:
        tg.send(chat, "❌ 열린 터미널 없음")
        return None
    if len(marks) == 1:
        return marks[0][0]   # 단일 → 즉시실행 힌트
    label, _ = ACTIONS[action]
    kb = build_slot_keyboard(marks, action)
    tg.send(chat, label, reply_markup={"inline_keyboard": kb})
    return None


def rerun_with_slot(cmd: "Command", msg: "Message", ctx: "CommandContext",
                    action: str, num: int) -> None:
    """가상 Message("/<trigger> <num>") 만들어 cmd.handle() 재진입.

    기존 handle() 재사용 = 명령 코드 중복 0. parts[1] 있으므로 정상 경로 진입.
    """
    from ..commands.base import Message
    _, trigger = ACTIONS[action]
    fake = Message(chat_id=msg.chat_id, text=f"/{trigger} {num}", raw={})
    cmd.handle(fake, ctx)
