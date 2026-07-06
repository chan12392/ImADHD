"""텔레그램 명령 추상 인터페이스.

새 명령(/status 등) 추가 시 Command 구현체 하나 추가하면 됨. core 변경 없음.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
    # 선택모드 대기 상태: chat_id -> (slot_num, timestamp).
    # 버튼 클릭 시 등록, 다음 본문 메시지 주입 시 소비.
    pending: dict = field(default_factory=dict)
    # 고정 타겟(sticky) 상태: chat_id -> slot_num.
    # /use N 으로 설정 → 이후 번호 없는 본문을 해당 슬롯으로 자동 주입.
    # /use off 또는 슬롯 사망 시 해제. data_dir/sticky.json 영속.
    sticky: dict = field(default_factory=dict)


class Command(ABC):
    """텔레그램 메시지 하나를 처리할지 결정하고 실행."""

    @abstractmethod
    def match(self, msg: Message) -> bool: ...

    @abstractmethod
    def handle(self, msg: Message, ctx: CommandContext) -> None: ...


def resolve_active_slot(
    msg: Message,
    ctx: CommandContext,
    number: int,
    *,
    missing_message: str | None = None,
    dead_message: str | None = None,
    check_alive: bool = True,
) -> tuple[int | None, Any | None]:
    """Resolve a slot and optionally reject/release it when the transport is dead."""
    info = ctx.registry.get(number)
    if not info:
        ctx.telegram.send(msg.chat_id, missing_message or f"❌{number}번 터미널 없음")
        return None, None
    if check_alive and not ctx.transport.is_alive(info.to_dict()):
        ctx.registry.release(number)
        ctx.telegram.send(msg.chat_id, dead_message or f"⚠️{number}번 터미널 종료")
        return None, None
    return number, info
