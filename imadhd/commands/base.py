"""텔레그램 명령 추상 인터페이스.

새 명령(/status 등) 추가 시 Command 구현체 하나 추가하면 됨. core 변경 없음.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    chat_id: str
    text: str
    raw: dict   # 원본 update payload


@dataclass
class CommandContext:
    """명령 실행에 필요한 의존성 주입용."""
    settings: "object"          # Settings
    registry: "object"          # Registry
    transport: "object"         # Transport
    telegram: "object"          # TelegramClient (회신용)


class Command(ABC):
    """텔레그램 메시지 하나를 처리할지 결정하고 실행."""

    @abstractmethod
    def match(self, msg: Message) -> bool: ...

    @abstractmethod
    def handle(self, msg: Message, ctx: CommandContext) -> None: ...
