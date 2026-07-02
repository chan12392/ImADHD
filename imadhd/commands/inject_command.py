"""N️⃣ 명령: 숫자이모지 파싱 → 사전체크 → (선택모드 pending | 즉시주입).

두 흐름:
  A) 버튼 클릭(번호+상태마크만): 선택모드 pending 등록 (안내 생략, 채팅 최소)
     → router가 다음 본문 메시지를 해당 번호로 주입 (PENDING_TTL 초 내)
  B) N️⃣<본문> 직접 타이핑: 즉시 주입
"""
from __future__ import annotations

import time

from .base import Command, Message, CommandContext


def _debug_log(line: str) -> None:
    try:
        from pathlib import Path
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# 숫자이모지 → 숫자 매핑 (1..6, 여유분 7..9 포함)
EMOJI_TO_NUM = {
    "1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5, "6️⃣": 6,
    "7️⃣": 7, "8️⃣": 8, "9️⃣": 9,
}

PENDING_TTL = 300  # 선택 대기 5분 초과 → 자동 해제(초)


class InjectCommand(Command):
    def match(self, msg: Message) -> bool:
        return bool(msg.text) and _starts_with_num_emoji(msg.text)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        num = parse_leading_number(msg.text)
        if num is None:
            return
        info = ctx.registry.get(num)
        if not info:
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 없음")
            return
        if not ctx.transport.is_alive(info.to_dict()):
            ctx.registry.release(num)
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 종료")
            return
        body = msg.text[len(leading_emoji(msg.text)):].strip()
        # A) 버튼 클릭(번호+상태마크, 점 구분 포함) → 선택모드 pending 토글
        clean = body.replace(".", "").strip()
        if not clean or clean in {"⭕", "❌", "📝"}:
            chat = str(msg.chat_id)
            existing = ctx.pending.get(chat)
            if existing and existing[0] == num:
                del ctx.pending[chat]                       # 같은 번호 재클릭 → 대기 취소
                _debug_log(f"[select] num={num} pending cancelled")
            else:
                ctx.pending[chat] = (num, time.time())      # 신규/다른 번호 → 대기 교체
                _debug_log(f"[select] num={num} pending set")
            return
        # B) 본문 있으면 즉시 주입
        do_inject(ctx, num, body, msg.chat_id)


def do_inject(ctx: CommandContext, num: int, body: str, chat_id: str) -> None:
    """주입 공통 로직: alive 재체크 + 본문 정규화 + 주입 + busy 표시.

    InjectCommand(즉시 주입) 와 router(pending 본문 주입) 모두 사용.
    """
    info = ctx.registry.get(num)
    if not info:
        ctx.telegram.send(chat_id, f"❌ {num}번 터미널 없음")
        return
    if not ctx.transport.is_alive(info.to_dict()):
        ctx.registry.release(num)
        ctx.telegram.send(chat_id, f"❌ {num}번 터미널 종료")
        return
    _debug_log(f"[inject] num={num} hwnd={info.hwnd} pid={info.pid} session={info.session_id[:8]}")
    # 한 줄 주입: \n은 CC 터미널에서 Enter(제출)로 작동해 분할되므로 제거
    body = " ".join(body.split()) or "(빈 입력)"
    # 마커는 CLAUDE.md 규칙 트리거([텔레그램에서 온 요청])만.
    # CC 규칙이 자동으로 "1~2문장 짧게 답 + 끝에 텔레그램으로 답변 출력" 수행.
    inject_text = f"{body} [텔레그램에서 온 요청]"
    ctx.registry.set_status(num, "busy")   # 📝 작업중 표시
    ctx.transport.inject(info.to_dict(), inject_text)


def _starts_with_num_emoji(text: str) -> bool:
    return any(text.startswith(e) for e in EMOJI_TO_NUM)


def parse_leading_number(text):
    """선두 숫자이모지 → int. 없으면 None."""
    if not text:
        return None
    for emoji, n in EMOJI_TO_NUM.items():
        if text.startswith(emoji):
            return n
    return None


def leading_emoji(text):
    """선두 숫자이모지 문자열 반환. 없으면 ''."""
    if not text:
        return ""
    for emoji in EMOJI_TO_NUM:
        if text.startswith(emoji):
            return emoji
    return ""
