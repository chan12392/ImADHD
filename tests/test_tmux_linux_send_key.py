"""tmux_linux transport 의 send_key(/stop Linux 지원) 단위 테스트.

2026-07-08 추가: Windows(sendkeys_win)의 /stop ESC 전송을 Linux/tmux 에서도
지원하기 위해 TmuxLinuxTransport.send_key 를 추가. VK_ESCAPE → tmux C-c.
실제 tmux 호출은 subprocess.run 을 mock 하여 검증.
"""
import subprocess

import pytest

from imadhd.transports.base import InjectResult
from imadhd.transports.tmux_linux import TmuxLinuxTransport


def _mk_target(tmux_pane="%7"):
    return {"tmux_pane": tmux_pane}


def test_send_key_escape_sends_ctrl_c(monkeypatch):
    """/stop(VK_ESCAPE=0x1B) → tmux send-keys C-c."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class _R:
            returncode = 0
            stdout = ""
        return _R()

    monkeypatch.setattr("imadhd.transports.tmux_linux._run", fake_run)
    monkeypatch.setattr("imadhd.transports.tmux_linux._has_session", lambda t: True)

    res = TmuxLinuxTransport().send_key(_mk_target(), 0x1B)
    assert res.delivered is True
    assert res.method == "tmux-sendkey"
    assert ["tmux", "send-keys", "-t", "%7", "C-c"] in calls


def test_send_key_dead_session_not_delivered(monkeypatch):
    """tmux 세션 없으면 dead → delivered=False."""
    monkeypatch.setattr("imadhd.transports.tmux_linux._has_session", lambda t: False)
    monkeypatch.setattr("imadhd.transports.tmux_linux._run", lambda *a, **k: None)

    res = TmuxLinuxTransport().send_key(_mk_target(), 0x1B)
    assert res.delivered is False
    assert "dead" in res.note


def test_send_key_unsupported_vk_rejected(monkeypatch):
    """ESC(0x1B) 외 vk 는 안전하게 거부(현재 /stop 만 지원)."""
    monkeypatch.setattr("imadhd.transports.tmux_linux._has_session", lambda t: True)
    monkeypatch.setattr("imadhd.transports.tmux_linux._run", lambda *a, **k: None)

    res = TmuxLinuxTransport().send_key(_mk_target(), 0x0D)  # ENTER
    assert res.delivered is False
    assert "unsupported" in res.note


def test_send_key_subprocess_exception_not_delivered(monkeypatch):
    """tmux 호출 예외 시 delivered=False + 진단 note."""
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd=a[0] if a else [], timeout=5)

    monkeypatch.setattr("imadhd.transports.tmux_linux._has_session", lambda t: True)
    monkeypatch.setattr("imadhd.transports.tmux_linux._run", boom)

    res = TmuxLinuxTransport().send_key(_mk_target(), 0x1B)
    assert res.delivered is False
    assert "실패" in res.note


def test_send_key_uses_fallback_when_no_pane(monkeypatch):
    """tmux_pane 빈 타겟 → IMADHD_TMUX_PREFIX 폴백 타겟으로 C-c 전송."""
    monkeypatch.delenv("IMADHD_TMUX_PREFIX", raising=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class _R:
            returncode = 0
            stdout = ""
        return _R()

    # 모듈 리로드로 TMUX_TARGET 전역값 확정(import 시점 평가).
    import importlib
    import imadhd.transports.tmux_linux as tl
    importlib.reload(tl)
    monkeypatch.setattr(tl, "_run", fake_run)
    monkeypatch.setattr(tl, "_has_session", lambda t: True)

    res = tl.TmuxLinuxTransport().send_key({"tmux_pane": ""}, 0x1B)
    assert res.delivered is True
    assert ["tmux", "send-keys", "-t", "claude", "C-c"] in calls
