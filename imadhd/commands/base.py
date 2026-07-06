"""텔레그램 명령 추상 인터페이스.

새 명령(/status 등) 추가 시 Command 구현체 하나 추가하면 됨. core 변경 없음.
"""
from __future__ import annotations

import re
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


# 선행 이모지/기호/공백 strip — ReplyKeyboard 버튼 텍스트("📋 list")를
# 슬래시 명령으로 정규화. 번호 이모지(1️⃣, InjectCommand 담당)에는 적용 안 함:
# match()에서만 쓰고 InjectCommand.match()는 그대로.
# 범위: 구두·기호(0x2000-0x2BFF, ✖❓⏹ 등) + 이모지(0x1F000-0x1FAFF, 🆕📋🎯 등).
#   주의: 0x2600 시작이면 ⏹(U+23F9), 0x1F300 시작이면 🆕(U+1F195) 구멍 → 확장.
_LEAD_NOISE = re.compile(
    r'^[\s'
    r'\U00002000-\U00002BFF'   # 구두·화살표·수학·키보드·잡기호 (✖❓⏹⏭☀)
    r'\U0001F000-\U0001FAFF'   # 이모지 전역 (🆕📋📌📂🎯🩺🔄)
    r'\U0001F1E6-\U0001F1FF'   # 국기
    r'‍'                  # ZWJ
    r'️'                  # variation selector
    r']+',
    re.UNICODE,
)

# 버튼 라벨(이모지+영문, 슬래시 없음)이 탭되면 라우터 매칭을 위해
# bare 영문 첫 토큰에 "/" 를 붙인다. setup_commands 와 동기화 필요.
_KNOWN_CMDS = {
    "list", "pin", "new", "open", "close", "stop",
    "use", "doctor", "help", "update-adhd", "update_adhd",
}


def normalize_command(text: str | None) -> str:
    """ReplyKeyboard 버튼 텍스트("📋 list", "✖️ close") → "/list", "/close".

    선행 이모지·기호·공백 strip 후 lower. 첫 토큰이 알려진 명령이고 "/" 가 없으면
    prepend (버튼 = 이모지+영문, 슬래시 없음 지원). Command.match() 전처리용.
    """
    t = _LEAD_NOISE.sub('', (text or '').strip()).lower()
    first = t.split(None, 1)[0] if t else ''
    if first and first in _KNOWN_CMDS:
        return '/' + t
    return t


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
