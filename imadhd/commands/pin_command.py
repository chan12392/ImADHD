"""/공지 명령: 슬롯 상태 공지(Pin) 생성.
확장: PinBoard 주입. /공지 /pin /상태 트리거.
"""
from __future__ import annotations

import logging

from .base import Command, Message, CommandContext, normalize_command

_log = logging.getLogger("imadhd")


class PinCommand(Command):
    TRIGGERS = {"/공지", "/pin", "/상태"}

    def __init__(self, board):
        self.board = board

    def match(self, msg: Message) -> bool:
        n = normalize_command(msg.text)
        _log.info("PinCommand.match text=%r norm=%r hit=%s", msg.text, n, n in self.TRIGGERS)
        return n in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        _log.info("PinCommand.handle create()")
        self.board.create()
        self.board.refresh_if_changed()
