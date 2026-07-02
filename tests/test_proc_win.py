"""proc_win 테스트 (Windows 전용)."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ctypes")

from imadhd.core.proc_win import exists, find_ancestor, snapshot  # noqa: E402


def test_snapshot_has_self():
    procs = snapshot()
    assert os.getpid() in procs


def test_exists_self_true():
    assert exists(os.getpid()) is True


def test_exists_fake_pid_false():
    assert exists(987654321) is False


def test_find_ancestor_unknown_returns_none():
    assert find_ancestor(os.getpid(), "no_such_exe_zzz") is None
