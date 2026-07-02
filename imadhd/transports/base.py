"""터미널 입력 transport 추상 인터페이스.

새 입력 방식(tmux/pty) 추가 시 이 인터페이스만 구현하면 core 변경 없음.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class InjectResult:
    delivered: bool        # 입력이 실제로 도달했는지 (확신 가능할 때만 True)
    method: str            # 사용된 방식 (예: "focus", "postmessage-bg")
    note: str = ""         # 부가 정보/경고


class Transport(ABC):
    """터미널에 텍스트를 주입하는 방식."""

    @abstractmethod
    def inject(self, target: dict, text: str, background: bool = False) -> InjectResult:
        """target(registry 의 session dict) 에 text 주입. 끝에 ENTER.

        background=True 면 포커스 안 빼앗는 방식 시도(베타, 도달 보장 없음).
        기본(False)=포커스 강제(v1, 확실).
        """

    @abstractmethod
    def is_alive(self, target: dict) -> bool:
        """해당 세션 터미널이 살아있는지(입력 직전 사전체크용)."""
