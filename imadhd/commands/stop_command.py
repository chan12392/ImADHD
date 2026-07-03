"""/stop N 명령: N번 터미널 현재 작업 중단 (ESC 키 전송).

CC TUI 에서 ESC = 진행 중 작업(generation/tool) 중단. /stop 으로 원격 중단.
transport.send_key(VK_ESCAPE) — 포커스 강제 후 keybd_event.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext

VK_ESCAPE = 0x1B


class StopCommand(Command):
    TRIGGERS = ("/stop", "/중단", "/정지")

    def match(self, msg: Message) -> bool:
        t = (msg.text or "").strip().lower()
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = (msg.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            ctx.telegram.send(msg.chat_id, "사용법: /stop 1  → 1번 터미널 작업 중단(ESC)")
            return
        num = int(parts[1])
        info = ctx.registry.get(num)
        if not info:
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 없음")
            return
        if not ctx.transport.is_alive(info.to_dict()):
            ctx.registry.release(num)
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 종료됨")
            return
        try:
            ctx.transport.send_key(info.to_dict(), VK_ESCAPE)
        except NotImplementedError:
            ctx.telegram.send(msg.chat_id, "⚠️ 이 transport 는 키 전송 미지원")
            return
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"⚠️ {num}번 중단 전송 실패: {e}")
            return
        ctx.telegram.send(msg.chat_id, f"⏹ {num}번 작업 중단(ESC) 전송")
