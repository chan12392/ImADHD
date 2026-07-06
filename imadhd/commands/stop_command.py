"""/stop N 명령: N번 터미널 현재 작업 중단 (ESC 키 전송).

CC TUI 에서 ESC = 진행 중 작업(generation/tool) 중단. /stop 으로 원격 중단.
transport.send_key(VK_ESCAPE) — 포커스 강제 후 keybd_event.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext, normalize_command, resolve_active_slot
from ..core import slot_picker

VK_ESCAPE = 0x1B


class StopCommand(Command):
    TRIGGERS = ("/stop", "/중단", "/정지")

    def match(self, msg: Message) -> bool:
        t = normalize_command(msg.text)
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = normalize_command(msg.text).split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            sticky_num = (ctx.sticky or {}).get(msg.chat_id)
            picked = slot_picker.send_picker(
                ctx.telegram, msg.chat_id, "stop", ctx.registry, sticky_num)
            if picked is not None:
                slot_picker.rerun_with_slot(self, msg, ctx, "stop", picked)
            return
        num = int(parts[1])
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            dead_message=f"❌ {num}번 터미널 종료됨",
        )
        if not info:
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
