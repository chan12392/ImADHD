"""/list (또는 /터미널) 명령: 현재 활성 세션 목록 텔레그램 전송."""
from __future__ import annotations

from .base import Command, Message, CommandContext


class ListCommand(Command):
    TRIGGERS = {"/list", "/터미널", "/terminals", "/세션"}

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip().lower() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        raise NotImplementedError("implemented in plan step")
