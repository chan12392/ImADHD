"""/help 명령: 사용법 안내 텍스트 전송.

명령 세트 중앙 안내. 신규 사용자 온보딩 + 명령 잊었을 때 참조.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext, normalize_command

HELP_TEXT = (
    "🎮 ImADHD — 터미널 원격 조종\n"
    "\n"
    "• 1️⃣~6️⃣ 또는 /1 ~/6\n"
    "    N번 터미널로 메시지 전송\n"
    "    번호만 보내면 다음 메시지를 N번으로 전송(선택모드)\n"
    "• /list — 활성 터미널 목록\n"
    "• /new N — N번 터미널 새 대화(/clear)\n"
    "• /open — 새 터미널 생성(홈 디렉토리 기반, CC resume 세션 인식)\n"
    "• /close N — N번 터미널 닫기\n"
    "• /stop N — N번 작업 중단(ESC)\n"
    "• /use N — N번 터미널 고정(이후 본문 자동 주입, 🎯 표시)\n"
    "• /use off — 고정 해제\n"
    "• /doctor — 진단(라우터·훅·pm2·봇 메뉴)\n"
    "• /update-adhd — ImADHD 갱신(git pull+pytest+restart)\n"
    "• /pin — 상태 보드 핀 새로고침\n"
    "• /help — 이 도움말\n"
    "\n"
    "터미널 종료 시 자동 ❌. PC 꺼지면 재부팅 후 수초 내 ❌."
)


class HelpCommand(Command):
    TRIGGERS = {"/help", "/도움", "/?"}

    def match(self, msg: Message) -> bool:
        return normalize_command(msg.text) in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        ctx.telegram.send(msg.chat_id, HELP_TEXT)
