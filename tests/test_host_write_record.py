"""_write_record 단위 테스트: text/\\r 분리 전송 (bracketed-paste 회피).

2026-07-07: 긴 본문 주입 시 CC TUI 가 연속 입력을 paste 로 감지해 끝 \\r 을
줄바꿈(제출 아님) 처리하는 현상 방지 → text 와 \\r 분리 + 사이 sleep.
"""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("host.py is Windows-only", allow_module_level=True)
try:
    import win32file  # noqa: F401
    import win32pipe  # noqa: F401
except ImportError:
    pytest.skip("pywin32 not available", allow_module_level=True)

from imadhd import host


class _FakePty:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.alive = True

    def isalive(self) -> bool:
        return self.alive

    def write(self, s: str) -> None:
        self.writes.append(s)


def test_write_record_splits_text_and_enter(monkeypatch):
    """text 와 \\r 분리 전송 + 사이 sleep. paste 감지창 탈출."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    host._write_record(pty, "이미지 수신: C:\\x\\y.jpg 캡션".encode("utf-8"))
    # 두 번 write: 본문, 그리고 단독 \r.
    assert len(pty.writes) == 2
    assert pty.writes[0].startswith("이미지 수신")
    assert "\r" not in pty.writes[0]          # 본문에 \r 섞이면 조기 제출 위험
    assert pty.writes[1] == "\r"


def test_write_record_sleep_between_writes(monkeypatch):
    """text→\\r 사이 sleep 1회 호출(0.08s). paste 종료 대기."""
    slept: list[float] = []
    monkeypatch.setattr(host.time, "sleep", lambda s: slept.append(s))
    host._write_record(_FakePty(), b"hello")
    assert len(slept) == 1
    assert slept[0] == pytest.approx(0.08)


def test_write_record_dead_pty_skipped(monkeypatch):
    """isalive False → write 미호출, 예외 없이 통과."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    pty.alive = False
    host._write_record(pty, b"x")
    assert pty.writes == []


def test_write_record_invalid_utf8_replaces(monkeypatch):
    """깨진 바이트 → replace(예외 발생 x, \\r 만 전송되지 않고 안전)."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    host._write_record(pty, b"\xff\xfe bad")
    assert len(pty.writes) == 2              # replace 된 text + \r
    assert pty.writes[1] == "\r"
