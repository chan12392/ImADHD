"""_write_record 단위 테스트: 본문 청크 분할 write + 단독 \\r 제출.

2026-07-07 v2: 통째 write 시 긴 본문이 CC TUI paste 감지에 걸려 끝 \\r 이
줄바꿈(제출 아님) = "입력창에만 남음" 간헐 실패(#38) → 본문 8자 청크 분할 +
15ms sleep(사람 타이핑 흉내)로 paste 감지 회피. 마지막 단독 \\r(submit).
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


def test_write_record_chunks_text_and_enter(monkeypatch):
    """본문 8자 청크 분할 + 마지막 단독 \\r."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    host._write_record(pty, "이미지 수신: C:\\x\\y.jpg 캡션".encode("utf-8"))
    assert pty.writes[-1] == "\r"                       # 마지막 = submit
    body = "".join(pty.writes[:-1])
    assert body.startswith("이미지 수신")
    assert "\r" not in body                             # 청크에 \r 섞이면 조기 제출
    assert all(len(c) <= 8 for c in pty.writes[:-1])    # 청크 한계
    assert len(pty.writes) >= 3                         # 본문 25자 → 청크 4 + \r


def test_write_record_sleeps_between_chunks(monkeypatch):
    """청크간 0.015 + 본문 후 0.08(\\r 직전)."""
    slept: list[float] = []
    monkeypatch.setattr(host.time, "sleep", lambda s: slept.append(s))
    host._write_record(_FakePty(), b"0123456789abcdef")   # 16자 = 청크 2개
    assert slept.count(0.015) == 2
    assert 0.08 in slept


def test_write_record_dead_pty_skipped(monkeypatch):
    """isalive False → write 미호출, 예외 없이 통과."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    pty.alive = False
    host._write_record(pty, b"x")
    assert pty.writes == []


def test_write_record_invalid_utf8_replaces(monkeypatch):
    """깨진 바이트 → replace(예외 x). 마지막은 \\r."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    host._write_record(pty, b"\xff\xfe bad")
    assert pty.writes[-1] == "\r"
    assert len(pty.writes) >= 2


def test_write_record_short_text_single_chunk(monkeypatch):
    """단문(8자 이하) = 청크 1개 + \\r = 2회 write."""
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pty = _FakePty()
    host._write_record(pty, b"hi")
    assert pty.writes == ["hi", "\r"]
