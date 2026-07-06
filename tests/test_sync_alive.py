"""sync_alive 런타임 자가치유 테스트 (SessionStart 훅 의존 보완).

목적: 훅이 안 돈 CC(일반 claude·/resume·pid 교체)를 라우터 매 틱이
발견해 register_alive_cc 로 지연 등록하는 흐름 검증.
"""
from __future__ import annotations

from types import SimpleNamespace

import imadhd.core.proc_win as proc_win_mod
import imadhd.core.router as router_mod
import imadhd.hooks.register_hook as register_hook_mod
from imadhd.core.router import sync_alive


def _slot(num: int, pid: int, hwnd: int = 0) -> SimpleNamespace:
    return SimpleNamespace(number=num, pid=pid, hwnd=hwnd)


class _FakeReg:
    """active() 만 쓰는 최소 가짜 registry."""

    def __init__(self, slots=None):
        self._slots = slots or []

    def active(self):
        return list(self._slots)


def _patch(monkeypatch, claude_pids, reg, hwnd_valid=None):
    calls: list[int] = []

    def fake_register(cc_pid, r, force_slot=None):
        calls.append(int(cc_pid))
        return len(calls)

    monkeypatch.setattr(proc_win_mod, "claude_pids", lambda: list(claude_pids))
    monkeypatch.setattr(register_hook_mod, "register_alive_cc", fake_register)
    if hwnd_valid is not None:
        monkeypatch.setattr(router_mod, "_hwnd_valid", hwnd_valid)
    return calls


def test_empty_registry_one_cc_registers_once(monkeypatch):
    """registry 공란 + claude.exe 1 → register 1회."""
    calls = _patch(monkeypatch, [1976], _FakeReg([]))
    n = sync_alive(_FakeReg([]))
    assert calls == [1976]
    assert n == 1


def test_already_registered_valid_hwnd_skipped(monkeypatch):
    """등록된 pid + 유효 hwnd → 재호출 없음(멱등)."""
    _patch(monkeypatch, [1976], _FakeReg([_slot(1, 1976, hwnd=999)]),
           hwnd_valid=lambda h: True)
    calls = _patch(monkeypatch, [1976], _FakeReg([_slot(1, 1976, hwnd=999)]),
                   hwnd_valid=lambda h: True)
    n = sync_alive(_FakeReg([_slot(1, 1976, hwnd=999)]))
    assert calls == []
    assert n == 0


def test_registered_pid_invalid_hwnd_refreshes(monkeypatch):
    """등록된 pid 나 hwnd 무효(0) → register 재호출(hwnd 갱신)."""
    calls = _patch(monkeypatch, [1976], _FakeReg([_slot(1, 1976, hwnd=0)]),
                   hwnd_valid=lambda h: h != 0)
    n = sync_alive(_FakeReg([_slot(1, 1976, hwnd=0)]))
    assert calls == [1976]
    assert n == 1


def test_no_claude_running_noop(monkeypatch):
    """claude.exe 0개 → 아무것도 안 함."""
    calls = _patch(monkeypatch, [], _FakeReg([]))
    n = sync_alive(_FakeReg([]))
    assert calls == []
    assert n == 0


def test_multiple_cc_all_unregistered(monkeypatch):
    """CC 2개 둘 다 미등록 → 둘 다 register(auto 주입은 여전히 active==1 조건)."""
    calls = _patch(monkeypatch, [1976, 27548], _FakeReg([]))
    n = sync_alive(_FakeReg([]))
    assert calls == [1976, 27548]
    assert n == 2


def test_mixed_one_registered_one_new(monkeypatch):
    """1개 등록(유효hwnd) + 1개 미등록 → 미등록건만 register."""
    calls = _patch(monkeypatch, [1976, 27548],
                   _FakeReg([_slot(1, 1976, hwnd=999)]),
                   hwnd_valid=lambda h: True)
    n = sync_alive(_FakeReg([_slot(1, 1976, hwnd=999)]))
    assert calls == [27548]
    assert n == 1
