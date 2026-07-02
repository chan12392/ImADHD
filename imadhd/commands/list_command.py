"""/list (또는 /터미널) 명령: 현재 활성 세션 목록 텔레그램 전송."""
from __future__ import annotations

from .base import Command, Message, CommandContext


class ListCommand(Command):
    TRIGGERS = {"/list", "/터미널", "/terminals", "/세션"}

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip().lower() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        from .inject_command import EMOJI_TO_NUM
        items = ctx.registry.active()
        if not items:
            ctx.telegram.send(msg.chat_id, "활성 터미널 없음")
            return
        inv = {v: k for k, v in EMOJI_TO_NUM.items()}
        lines = [
            f"{inv.get(i.number, '?')} #{i.number} PID {i.pid} — {i.cwd}"
            for i in items
        ]
        ctx.telegram.send(msg.chat_id, "\n".join(lines))
