"""tests/test_host.py — ImADHD PTY-bridge host (`py -m imadhd.host`).

완전히 격리된 서브프로세스 테스트:
  - 실제 claude/telegram 없이 줄-에코 더미 자식으로 host 를 spawn.
  - 더미 자식이 IMADHD_HOST_PID 배너(자식 env 에서 읽은 host.py pid) 출력.
  - 테스트가 그 host_pid 로 파이프 이름(imadhd-stdin-<host_pid>) 을 구성해 주입.
  - 자식 exit 후 host 도 정상 종료(행업 없음) 검증.

B-근본(2026-07-06): 파이프 이름이 slot 이 아니라 host.py 프로세스 pid.
고정 PIPE_NAME 상수 대신 배너에서 읽은 host_pid 로 동적 구성.

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

# 더미 자식: banner 로 IMADHD_HOST_PID 출력 → 줄 단위 에코 → QUIT 입력 시 종료.
# host.py 가 자식 env 에 IMADHD_HOST_PID=<os.getpid()> 를 주입하므로 자식이 읽어 출력.
DUMMY_CHILD = (
    "import sys, os\n"
    "sys.stdout.write('HOST_PID=' + (os.environ.get('IMADHD_HOST_PID') or '') + '\\n')\n"
    "sys.stdout.flush()\n"
    "while True:\n"
    "    line = sys.stdin.readline()\n"
    "    if line == '' or 'QUIT' in line:\n"
    "        break\n"
    "    sys.stdout.write('ECHO ' + line.rstrip('\\r\\n') + '\\n')\n"
    "    sys.stdout.flush()\n"
)


def _pipe_name_for(host_pid: int) -> str:
    """host_pid → 파이프 경로. host.py 의 NAMED_PIPE_PREFIX 와 일치해야 함."""
    return f"\\\\.\\pipe\\imadhd-stdin-{host_pid}"


def _repo_root() -> str:
    # tests/ 의 부모 디렉토리 = repo root.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spawn_host():
    """host 를 더미 자식과 함께 서브프로세스로 기동."""
    env = dict(os.environ)
    # host 가 자식에게 IMADHD_HOST_PID 를 주입하므로 부모 env 잔재는 비움.
    env.pop("IMADHD_HOST_PID", None)
    env.pop("IMADHD_WANT_SLOT", None)
    return subprocess.Popen(
        [
            sys.executable, "-u", "-m", "imadhd.host",
            "--",
            sys.executable, "-u", "-c", DUMMY_CHILD,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_repo_root(),
        env=env,
    )


def _wait_pipe_connectable(pipe_name: str, timeout: float = 10.0):
    """네임드파이프가 클라이언트로 연결 가능해질 때까지 재시도. 핸들 또는 None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                pipe_name,
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
        # 1) 더미 자식 배너(HOST_PID=N) 대기 → host_pid 동적 획득
        banner = _read_until(proc.stdout, lambda l: b"HOST_PID=" in l, timeout=15)
        host_pid_str = None
        for l in banner:
            if b"HOST_PID=" in l:
                host_pid_str = l.split(b"HOST_PID=", 1)[1].strip()
                break
        assert host_pid_str and host_pid_str.isdigit(), \
            f"IMADHD_HOST_PID 배너 누락/비정수: {banner!r}"
        host_pid = int(host_pid_str)
        pipe_name = _pipe_name_for(host_pid)

        # 2) 네임드파이프가 클라이언트로 연결 가능해질 때까지 대기
        handle = _wait_pipe_connectable(pipe_name, timeout=10)
        assert handle is not None, f"파이프가 제때 열리지 않음: {pipe_name}"

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
        handle2 = _wait_pipe_connectable(pipe_name, timeout=5)
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


def test_parse_args_defaults():
    from imadhd.host import parse_args
    # 인자 없음 → (slot_or_None, ['claude']). slot 은 이제 미사용이지만
    # parse_args 시그니처 호환성 유지.
    parsed = parse_args([])
    assert parsed[1] == ["claude"]
    # child args 전달
    assert parse_args(["--", "foo", "bar"])[1] == ["foo", "bar"]
    assert parse_args(["only"])[1] == ["only"]


def test_build_env_sets_host_pid(monkeypatch):
    """_build_env_string() 이 IMADHD_HOST_PID(=os.getpid()) 를 주입하고
    IMADHD_WANT_SLOT 잔재를 제거하는지 검증."""
    from imadhd.host import _build_env_string
    blob = _build_env_string()
    pairs = dict(p.split("=", 1) for p in blob.split("\0") if "=" in p and p)
    # _build_env_string 을 호출한 프로세스(=테스트 프로세스)의 pid 와 일치.
    assert pairs.get("IMADHD_HOST_PID") == str(os.getpid())
    # WANT_SLOT 잔재 제거(불일치 방지).
    assert "IMADHD_WANT_SLOT" not in pairs
