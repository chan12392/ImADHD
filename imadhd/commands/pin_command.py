"""/공지 명령: 슬롯 상태 공지(Pin) 생성.
확장: PinBoard 주입. /공지 /pin /상태 트리거.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext


class PinCommand(Command):
    TRIGGERS = {"/공지", "/pin", "/상태"}

    def __init__(self, board):
        self.board = board

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        self.board.create()
        self.board.refresh_if_changed()
