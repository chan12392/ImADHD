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

# 숫자이모지 → 숫자 매핑 (1..6, 여유분 7..9 포함)
EMOJI_TO_NUM = {
    "1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5, "6️⃣": 6,
    "7️⃣": 7, "8️⃣": 8, "9️⃣": 9,
}


class InjectCommand(Command):
    def match(self, msg: Message) -> bool:
        return bool(msg.text) and _starts_with_num_emoji(msg.text)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        raise NotImplementedError("implemented in plan step")


def _starts_with_num_emoji(text: str) -> bool:
    return any(text.startswith(e) for e in EMOJI_TO_NUM)
