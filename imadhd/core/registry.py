"""번호 ↔ 세션 매핑 레지스트리.

확장 포인트: Registry 인터페이스만 따르면 JSON 외에 DB/Redis 구현 가능.
현재는 단일 머신 JSONFileRegistry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class SessionInfo:
    number: int
    session_id: str
    hwnd: int
    pid: int
    cwd: str
    started_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class Registry(ABC):
    """번호 ↔ 세션 매핑 저장소 인터페이스."""

    @abstractmethod
    def claim_slot(self, session_id: str, hwnd: int, pid: int, cwd: str, started_at: str) -> int:
        """가장 낮은 빈 슬롯 할당. 반환=할당된 번호."""

    @abstractmethod
    def get(self, number: int) -> Optional[SessionInfo]:
        ...

    @abstractmethod
    def find_by_session(self, session_id: str) -> Optional[SessionInfo]:
        ...

    @abstractmethod
    def release(self, number: int) -> bool:
        ...

    @abstractmethod
    def active(self) -> list[SessionInfo]:
        ...


class JSONFileRegistry(Registry):
    """TODO: 원자적 쓰기(임시파일+rename), 파일 록."""

    def __init__(self, path: Path, max_slots: int = 6):
        self.path = path
        self.max_slots = max_slots
        raise NotImplementedError("implemented in plan step")
