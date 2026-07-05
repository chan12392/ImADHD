"""번호 ↔ 세션 매핑 레지스트리.

확장 포인트: Registry 인터페이스만 따르면 JSON 외에 DB/Redis 구현 가능.
현재는 단일 머신 JSONFileRegistry.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from .numberalloc import lowest_free


def _try_lock(f) -> bool:
    """비차단 배타락 시도. 성공 True."""
    if os.name == "nt":
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    if os.name == "nt":
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@dataclass
class SessionInfo:
    number: int
    session_id: str
    hwnd: int
    pid: int
    cwd: str
    started_at: str
    status: str = "idle"   # idle | busy (작업중 📝)

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
    def set_hwnd(self, number: int, hwnd: int) -> bool:
        """해당 슬롯의 hwnd 만 갱신(stale hwnd 복구용). status 는 보존."""

    @abstractmethod
    def sweep_dead(self, is_alive: Callable[["SessionInfo"], bool]) -> int:
        """is_alive(info)가 False인 슬롯 전부 release. 반환=정리된 개수."""


class JSONFileRegistry(Registry):
    """단일 머신 JSON 파일 레지스트리. 원자적 쓰기(임시파일+os.replace)."""

    def __init__(self, path, max_slots: int = 6):
        self.path = Path(path)
        self.max_slots = max_slots
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    @contextlib.contextmanager
    def _locked(self, timeout: float = 5.0):
        """배타 파일 락(Windows msvcrt). read-modify-write 구간을 프로세스 간
        직렬화해 SessionStart/Stop/UserPromptSubmit 훅이 거의 동시에 registry.json
        을 고치다 서로의 변경을 통째로 덮어쓰는 lost update 를 막는다
        (2026-07-04 session_id 덮어쓰기 사고와 같은 계열의 근본원인).
        락 획득 실패해도 timeout 후 그냥 진행 — 훅이 영구히 멈추는 것보다
        드문 레이스가 낫다(가용성 우선)."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.lock_path, "a+b")
        locked = False
        try:
            deadline = time.monotonic() + timeout
            while True:
                if _try_lock(f):
                    locked = True
                    break
                if time.monotonic() > deadline:
                    break
                time.sleep(0.05)
            yield
        finally:
            if locked:
                try:
                    _unlock(f)
                except OSError:
                    pass
            f.close()

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
        with self._locked():
            data = self._read()
            # 동일 session_id OR 동일 pid(CC 프로세스) → 기존 슬롯 재사용(덮어쓰기).
            # /resume·세션재개 로 session_id 가 바뀌어도 같은 CC(pid)면 같은 슬롯 유지.
            # 안 하면 같은 터미널이 session 변경마다 새 슬롯 점유 → "터미널 1개인데 N번 2개" 중복.
            for k, v in data.items():
                if v and (v.get("session_id") == session_id or v.get("pid") == pid):
                    num = int(k)
                    # 방어: 빈 session_id 호출(비정상/테스트성 훅 실행)이 pid 매칭만으로
                    # 기존 슬롯의 정상 session_id 를 지우면 Stop 훅의 find_by_session 이
                    # 끊겨 상태가 busy 로 영구 고정된다. 새 값이 비어 있으면 기존 값 보존.
                    effective_id = session_id or v.get("session_id", "")
                    data[k] = SessionInfo(num, effective_id, hwnd, pid, cwd, started_at).to_dict()
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
        with self._locked():
            data = self._read()
            key = str(number)
            if key in data and data[key]:
                data[key] = None
                self._write(data)
                return True
            return False

    def set_status(self, number: int, status: str) -> bool:
        with self._locked():
            data = self._read()
            v = data.get(str(number))
            if v:
                v["status"] = status
                self._write(data)
                return True
            return False

    def set_status_by_session(self, session_id: str, status: str) -> bool:
        with self._locked():
            data = self._read()
            for v in data.values():
                if v and v.get("session_id") == session_id:
                    v["status"] = status
                    self._write(data)
                    return True
            return False

    def set_hwnd(self, number: int, hwnd: int) -> bool:
        """해당 슬롯의 hwnd 만 갱신. status 보존(stale hwnd 복구 후에도 busy 유지)."""
        with self._locked():
            data = self._read()
            v = data.get(str(number))
            if v:
                v["hwnd"] = int(hwnd)
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
        with self._locked():
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
