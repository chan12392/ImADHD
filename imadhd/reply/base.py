"""답변 회신 전략 추상 인터페이스.

Stop 훅이 transcript 에서 답변을 뽑아 텔레그램으로 보내는 방식.
마커 기반이 기본. 향후 항상-회신 등 다른 전략 추가 가능.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ReplyPayload:
    session_id: str
    transcript_path: str
    assistant_text: str


class ReplyStrategy(ABC):
    @abstractmethod
    def should_reply(self, payload: ReplyPayload) -> bool: ...

    @abstractmethod
    def build_text(self, payload: ReplyPayload) -> str: ...
