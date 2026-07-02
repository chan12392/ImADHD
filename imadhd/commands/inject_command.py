"""N️⃣<본문> 명령: 숫자이모지 파싱 → 사전체크 → 주입 → ack.

흐름:
  1. 선두 숫자이모지(1️⃣..6️⃣) 파싱
  2. registry 조회
  3. transport.is_alive 사전체크 (죽었으면 슬롯 회수 + 에러 텔레그램)
  4. ack 전송 "📩 N번 ← ..."
  5. transport.inject (본문 + [텔레그램 요청 마커])
"""
from __future__ import annotations

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
        target = info.to_dict()
        alive = ctx.transport.is_alive(target)
        _debug_log(f"[inject] num={num} hwnd={info.hwnd} pid={info.pid} session={info.session_id[:8]} is_alive={alive}")
        if not alive:
            ctx.registry.release(num)
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 종료")
            return
        body = msg.text[len(leading_emoji(msg.text)):].strip() or "(빈 입력)"
        # 한 줄 주입: \n은 CC 터미널에서 Enter(제출)로 작동해 분할되므로 제거
        body = " ".join(body.split())
        inject_text = (
            f"{body}  [텔레그램에서 온 요청. 1~2문장으로 짧게 답하고 "
            f"답변 끝에 '{ctx.settings.reply_marker}' 출력]"
        )
        ctx.registry.set_status(num, "busy")   # 📝 작업중 표시
        ctx.transport.inject(target, inject_text)


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
