"""boot_check 단위테스트 — pm2 좀비(online/pid=None) 감지 & restart.

subprocess/time 을 monkeypatch 로 격리해 pm2 없이 로직 검증.
"""
from __future__ import annotations

from imadhd import boot_check


def _proc(name, status, pid):
    """pm2 jlist 원소 형태."""
    return {"name": name, "pid": pid, "pm2_env": {"status": status}}


# ---- is_zombie ----

def test_zombie_online_no_pid():
    assert boot_check.is_zombie(_proc("imadhd", "online", None)) is True
    assert boot_check.is_zombie(_proc("imadhd", "online", 0)) is True


def test_not_zombie_online_with_pid():
    assert boot_check.is_zombie(_proc("imadhd", "online", 25576)) is False
    assert boot_check.is_zombie(_proc("imadhd-watchdog", "online", 2656)) is False


def test_not_zombie_stopped_no_pid():
    # stopped/errored 는 boot_check 대상 아님 (pm2 자체 비정상 상태는 별도)
    assert boot_check.is_zombie(_proc("imadhd", "stopped", None)) is False
    assert boot_check.is_zombie(_proc("imadhd", "errored", None)) is False


def test_not_zombie_other_name():
    assert boot_check.is_zombie(_proc("mapgen", "online", None)) is False
    assert boot_check.is_zombie(_proc("skillops-export", "online", None)) is False


# ---- boot_check (subprocess 격리) ----

def _harness(monkeypatch, jlist_seq):
    """jlist_seq: list of list-of-proc. 매 _pm2_jlist 호출마다 하나씩 반환."""
    calls = {"restart": [], "jlist": 0}

    def fake_jlist():
        idx = calls["jlist"]
        calls["jlist"] += 1
        return jlist_seq[min(idx, len(jlist_seq) - 1)]

    def fake_run(args, **kwargs):
        # boot_check 는 shell=True 문자열로 호출 → 단언 편의를 위해 토큰화.
        calls["restart"].append(args.split() if isinstance(args, str) else list(args))
        return type("R", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()

    monkeypatch.setattr(boot_check, "_pm2_jlist", fake_jlist)
    monkeypatch.setattr(boot_check.subprocess, "run", fake_run)
    monkeypatch.setattr(boot_check.time, "sleep", lambda _s: None)
    return calls


def test_boot_check_no_zombies_no_restart(monkeypatch):
    calls = _harness(monkeypatch, [[_proc("imadhd", "online", 100), _proc("imadhd-watchdog", "online", 101)]])
    assert boot_check.boot_check() == 0
    assert calls["restart"] == []


def test_boot_check_restarts_single_zombie(monkeypatch):
    # 1회차: imadhd 좀비 → restart. 2회차: 정상 → 종료.
    calls = _harness(monkeypatch, [
        [_proc("imadhd", "online", None), _proc("imadhd-watchdog", "online", 101)],
        [_proc("imadhd", "online", 200), _proc("imadhd-watchdog", "online", 101)],
    ])
    assert boot_check.boot_check() == 0
    assert calls["restart"] == [["pm2", "restart", "imadhd"]]


def test_boot_check_restarts_both_zombies_at_once(monkeypatch):
    # 둘 다 좀비 → 한 번의 restart 호출에 두 이름(이번 사고 정확 패턴).
    calls = _harness(monkeypatch, [
        [_proc("imadhd", "online", None), _proc("imadhd-watchdog", "online", None)],
        [_proc("imadhd", "online", 300), _proc("imadhd-watchdog", "online", 301)],
    ])
    assert boot_check.boot_check() == 0
    assert calls["restart"] == [["pm2", "restart", "imadhd", "imadhd-watchdog"]]


def test_boot_check_persistent_zombie_returns_failure(monkeypatch):
    # 3회 retry 전부 좀비 → 여전히 좀비 → exit 1.
    calls = _harness(monkeypatch, [
        [_proc("imadhd", "online", None)],
        [_proc("imadhd", "online", None)],
        [_proc("imadhd", "online", None)],
        [_proc("imadhd", "online", None)],
    ])
    assert boot_check.boot_check() == 1
    assert len(calls["restart"]) == boot_check.MAX_ATTEMPTS


def test_boot_check_recovers_after_retries(monkeypatch):
    # 1,2회차 좀비 → 3회차 정상 → exit 0 (retry 효과).
    calls = _harness(monkeypatch, [
        [_proc("imadhd", "online", None)],
        [_proc("imadhd", "online", None)],
        [_proc("imadhd", "online", 999)],
        [_proc("imadhd", "online", 999)],
    ])
    assert boot_check.boot_check() == 0
