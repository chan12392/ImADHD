"""번호 ↔ 세션 매핑 레지스트리.

확장 포인트: Registry 인터페이스만 따르면 JSON 외에 DB/Redis 구현 가능.
현재는 단일 머신 JSONFileRegistry.
"""
from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from .numberalloc import lowest_free


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

    @abstractmethod
    def sweep_dead(self, is_alive: Callable[["SessionInfo"], bool]) -> int:
        """is_alive(info)가 False인 슬롯 전부 release. 반환=정리된 개수."""


class JSONFileRegistry(Registry):
    """단일 머신 JSON 파일 레지스트리. 원자적 쓰기(임시파일+os.replace)."""

    def __init__(self, path, max_slots: int = 6):
        self.path = Path(path)
        self.max_slots = max_slots
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    @staticmethod
    def _occupied(data: dict) -> set[int]:
        return {int(k) for k, v in data.items() if v}

    def claim_slot(self, session_id, hwnd, pid, cwd, started_at):
        data = self._read()
        # 동일 session_id 재시작 → 기존 슬롯 재사용(덮어쓰기)
        for k, v in data.items():
            if v and v.get("session_id") == session_id:
                num = int(k)
                data[k] = SessionInfo(num, session_id, hwnd, pid, cwd, started_at).to_dict()
                self._write(data)
                return num
        free = lowest_free(self._occupied(data), self.max_slots)
        if free is None:
            return None
        data[str(free)] = SessionInfo(free, session_id, hwnd, pid, cwd, started_at).to_dict()
        self._write(data)
        return free

    def get(self, number: int) -> Optional[SessionInfo]:
        data = self._read()
        v = data.get(str(number))
        return SessionInfo(**v) if v else None

    def find_by_session(self, session_id: str) -> Optional[SessionInfo]:
        data = self._read()
        for v in data.values():
            if v and v.get("session_id") == session_id:
                return SessionInfo(**v)
        return None

    def release(self, number: int) -> bool:
        data = self._read()
        key = str(number)
        if key in data and data[key]:
            data[key] = None
            self._write(data)
            return True
        return False

    def active(self) -> list[SessionInfo]:
        data = self._read()
        out: list[SessionInfo] = []
        for k in sorted(data, key=lambda x: int(x)):
            v = data[k]
            if v:
                out.append(SessionInfo(**v))
        return out

    def sweep_dead(self, is_alive: Callable[["SessionInfo"], bool]) -> int:
        data = self._read()
        removed = 0
        for k in list(data.keys()):
            v = data[k]
            if v and not is_alive(SessionInfo(**v)):
                data[k] = None
                removed += 1
        if removed:
            self._write(data)
        return removed
