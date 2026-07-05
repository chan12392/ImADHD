"""tests/test_host.py — ImADHD PTY-bridge host (`py -m imadhd.host`).

완전히 격리된 서브프로세스 테스트:
  - 실제 claude/telegram 없이 줄-에코 더미 자식으로 host 를 spawn.
  - `--slot N` 으로 결정론적 slot 고정 → 네임드파이프 클라이언트로 주입.
  - 자식 exit 후 host 도 정상 종료(행업 없음) 검증.

Windows 전용(pywinpty + pywin32). 다른 플랫폼은 스킵.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

# ── Module-level skips ──────────────────────────────────────────────

if sys.platform != "win32":
    pytest.skip("host.py is Windows-only (ConPTY + named pipes)", allow_module_level=True)

try:
    import win32file  # noqa: F401
    import win32pipe  # noqa: F401
    import pywintypes  # noqa: F401
except ImportError:
    pytest.skip("pywin32 not available", allow_module_level=True)

try:
    import winpty  # noqa: F401
except ImportError:
    pytest.skip("pywinpty not available", allow_module_level=True)


# ── Test fixtures ───────────────────────────────────────────────────

# 높은 slot 번호 — 실제 라우터/레지스트리 슬롯(1..6)과 충돌 회피.
SLOT = 7
PIPE_NAME = f"\\\\.\\pipe\\imadhd-slot-{SLOT}"

# 더미 자식: banner 로 IMADHD_WANT_SLOT 출력 → 줄 단위 에코 → QUIT 입력 시 종료.
DUMMY_CHILD = (
    "import sys, os\n"
    "sys.stdout.write('WANT_SLOT=' + (os.environ.get('IMADHD_WANT_SLOT') or '') + '\\n')\n"
    "sys.stdout.flush()\n"
    "while True:\n"
    "    line = sys.stdin.readline()\n"
    "    if line == '' or 'QUIT' in line:\n"
    "        break\n"
    "    sys.stdout.write('ECHO ' + line.rstrip('\\r\\n') + '\\n')\n"
    "    sys.stdout.flush()\n"
)


def _repo_root() -> str:
    # tests/ 의 부모 디렉토리 = repo root.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spawn_host():
    """host 를 더미 자식과 함께 서브프로세스로 기동."""
    env = dict(os.environ)
    # host 가 Settings.load() 를 시도하지 않도록(--slot 명시) 토큰 불필요.
    # 다만 IMADHD_WANT_SLOT 은 host 가 자식에게 주입하므로 여기서 비워둘 것.
    env.pop("IMADHD_WANT_SLOT", None)
    return subprocess.Popen(
        [
            sys.executable, "-u", "-m", "imadhd.host",
            "--slot", str(SLOT),
            "--",
            sys.executable, "-u", "-c", DUMMY_CHILD,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_repo_root(),
        env=env,
    )


def _wait_pipe_connectable(timeout: float = 10.0):
    """네임드파이프가 클라이언트로 연결 가능해질 때까지 재시도. 핸들 또는 None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            return handle
        except pywintypes.error:
            time.sleep(0.1)
    return None


def _read_until(lines_attr, predicate, timeout: float = 10.0) -> list[bytes]:
    """host stdout/stderr 파이프에서 한 줄씩 읽으며 predicate(line) 가 참이면 종료."""
    deadline = time.monotonic() + timeout
    collected: list[bytes] = []
    stream = lines_attr
    while time.monotonic() < deadline:
        line = stream.readline()
        if not line:
            time.sleep(0.05)
            continue
        collected.append(line)
        try:
            if predicate(line):
                break
        except Exception:
            pass
    return collected


# ── Tests ───────────────────────────────────────────────────────────

def test_import_clean():
    """`import imadhd.host` 가 부작용 없이 깨끗하게 import 되어야 한다."""
    import imadhd.host  # noqa: F401
    assert hasattr(imadhd.host, "main")


def test_host_pipe_inject_and_env():
    proc = _spawn_host()
    try:
        # 1) 더미 자식 배너(WANT_SLOT=N) 대기
        banner = _read_until(proc.stdout, lambda l: b"WANT_SLOT=" in l, timeout=15)
        assert any(b"WANT_SLOT=7" in l for l in banner), \
            f"IMADHD_WANT_SLOT 배너 누락: {banner!r}"

        # 2) 네임드파이프가 클라이언트로 연결 가능해질 때까지 대기
        handle = _wait_pipe_connectable(timeout=10)
        assert handle is not None, "파이프가 제때 열리지 않음"

        # 3) 주입: b"hello world\n" → host 가 "hello world\r" 을 PTY 에 기록
        #    → 더미 자식이 "ECHO hello world\n" 출력 → host stdout 으로 전달
        try:
            win32file.WriteFile(handle, b"hello world\n")
        finally:
            win32file.CloseHandle(handle)

        echoed = _read_until(proc.stdout, lambda l: b"ECHO hello world" in l, timeout=10)
        assert any(b"ECHO hello world" in l for l in echoed), \
            f"ECHO 줄 누락: {echoed!r}"

        # 4) 더미 자식 종료(QUIT 주입) → 자식 exit → host 도 같이 종료되어야 함
        handle2 = _wait_pipe_connectable(timeout=5)
        assert handle2 is not None, "두 번째 연결 실패(멀티커넥트 서버 아님?)"
        try:
            win32file.WriteFile(handle2, b"QUIT\n")
        finally:
            win32file.CloseHandle(handle2)

        # host 행업 없이 10초 안 종료되어야 함(acceptance: not hung).
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            pytest.fail("host 가 자식 exit 후 종료되지 않음(행업)")
        # 정상 종료 코드(0 또는 자식 코드). 음수 kill 이 아니면 OK.
        assert rc is not None
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_parse_args_defaults_and_slot():
    from imadhd.host import parse_args
    # 인자 없음 → (None, ['claude'])
    assert parse_args([]) == (None, ["claude"])
    # --slot N -- cmd args
    assert parse_args(["--slot", "3", "--", "foo", "bar"]) == (3, ["foo", "bar"])
    # --slot=N 형태
    assert parse_args(["--slot=5", "--", "x"]) == (5, ["x"])
    # -- 없이 child args
    assert parse_args(["--slot", "2", "mycmd"]) == (2, ["mycmd"])
    # --slot 없이 child args 만
    assert parse_args(["only"]) == (None, ["only"])


def test_build_env_sets_want_slot(monkeypatch):
    from imadhd.host import _build_env_string
    blob = _build_env_string(7)
    pairs = dict(p.split("=", 1) for p in blob.split("\0") if "=" in p and p)
    assert pairs.get("IMADHD_WANT_SLOT") == "7"
