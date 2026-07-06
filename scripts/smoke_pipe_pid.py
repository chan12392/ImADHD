"""B-근본 pid 파이프 통합 smoke 테스트 (봇/router 무관, 클론 안에서 안전).

검증 흐름 (라이브 /open→/2 ping 의 핵심 경로):
  1. host.py 를 더미 CC(에코) 자식으로 spawn.
  2. 자식이 IMADHD_HOST_PID 배너 출력 → host_pid 획득.
  3. 임시 registry.claim_slot(host_pid=P) → SessionInfo 저장(host_pid 필드).
  4. SessionInfo.to_dict() → PipeWinTransport.inject() → 파이프 경로 host_pid 매칭.
  5. 자식 에코(stdout) 로 주입 텍스트 도달 확인.

성공 = slot 불일치 원인(host.py slot ≠ register slot)이 pid 기반 파이프로 제거됨을
end-to-end 로 실측. 단위테스트(test_host/test_pipe_win) 가 묶인 흐름.

실행: py scripts/smoke_pipe_pid.py
종료코드 0 = 통과.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if os.name != "nt":
    print("SKIP: Windows 전용", flush=True)
    sys.exit(0)

try:
    import win32file, win32pipe, pywintypes  # noqa: F401,E401
except ImportError:
    print("SKIP: pywin32 없음", flush=True)
    sys.exit(0)

# 더미 CC: HOST_PID 배너 → 에코 → QUIT 종료 (test_host.DUMMY_CHILD 와 동일).
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


def _wait_pipe(pipe_name: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
        except pywintypes.error:
            time.sleep(0.1)
    return None


def _read_until(stream, needle: bytes, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    out = []
    while time.monotonic() < deadline:
        line = stream.readline()
        if not line:
            time.sleep(0.05)
            continue
        out.append(line)
        if needle in line:
            return line, out
    return None, out


def main() -> int:
    from imadhd.core.registry import JSONFileRegistry
    from imadhd.transports.pipe_win import PipeWinTransport

    env = dict(os.environ)
    env.pop("IMADHD_HOST_PID", None)
    env.pop("IMADHD_WANT_SLOT", None)

    print("[1/5] host.py + 더미 CC spawn...", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "imadhd.host", "--",
         sys.executable, "-u", "-c", DUMMY_CHILD],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(REPO), env=env,
    )
    try:
        banner, raw = _read_until(proc.stdout, b"HOST_PID=", timeout=15)
        assert banner, f"HOST_PID 배너 누락: {raw!r}"
        host_pid = int(banner.split(b"HOST_PID=", 1)[1].strip())
        print(f"      host_pid={host_pid} (자식 env 상속 확인)", flush=True)

        print("[2/5] 임시 registry.claim_slot(host_pid=...)...", flush=True)
        with tempfile.TemporaryDirectory() as td:
            reg = JSONFileRegistry(Path(td) / "reg.json", max_slots=6)
            num = reg.claim_slot("smoke-sess", hwnd=123, pid=9999, cwd="",
                                 started_at="now", host_pid=host_pid)
            assert num is not None, "slot 할당 실패"
            info = reg.get(num)
            assert info.host_pid == host_pid, \
                f"registry host_pid 불일치: {info.host_pid} != {host_pid}"
            print(f"      slot={num} host_pid={info.host_pid} 저장됨", flush=True)

            print("[3/5] to_dict() → PipeWinTransport.inject 경로 결정...", flush=True)
            target = info.to_dict()
            assert target["host_pid"] == host_pid, "to_dict host_pid 누락"
            tp = PipeWinTransport()
            # 파이프 존재해야 성공. host.py 가 host_pid 파이프 띄움.
            res = tp.inject(target, "smoke ping")
            print(f"      InjectResult: delivered={res.delivered} method={res.method} "
                  f"note={res.note}", flush=True)
            assert res.delivered, f"주입 실패: {res}"
            assert res.method == "pipe", \
                f"파이프 미경유(폴백): {res.method} — host_pid 매칭 의심"

            print("[4/5] 더미 CC 에코로 주입 도달 확인...", flush=True)
            echoed, raw2 = _read_until(proc.stdout, b"ECHO smoke ping", timeout=10)
            assert echoed, f"에코 누락(주입 미도달): {raw2!r}"
            print(f"      에코 확인: {echoed.strip().decode('utf-8','replace')}", flush=True)

            print("[5/5] 좀비/다중인스턴스 검증: 두 번째 host.py 다른 pid...", flush=True)
            # 동일 슬롯이어도 host_pid 다르면 다른 파이프 → 충돌 0 (좀비 회피 핵심).
            proc2 = subprocess.Popen(
                [sys.executable, "-u", "-m", "imadhd.host", "--",
                 sys.executable, "-u", "-c", DUMMY_CHILD],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(REPO), env=env,
            )
            try:
                banner2, _ = _read_until(proc2.stdout, b"HOST_PID=", timeout=15)
                host_pid2 = int(banner2.split(b"HOST_PID=", 1)[1].strip())
                assert host_pid2 != host_pid, \
                    "두 host.py 가 같은 pid (불가능한 상태)"
                # 두 파이프 모두 독립 존재 확인.
                n1 = _wait_pipe(rf"\\.\pipe\imadhd-stdin-{host_pid}", timeout=5)
                n2 = _wait_pipe(rf"\\.\pipe\imadhd-stdin-{host_pid2}", timeout=5)
                assert n1 and n2, f"파이프 중 하나 소실: n1={n1} n2={n2}"
                if n1: win32file.CloseHandle(n1)
                if n2: win32file.CloseHandle(n2)
                print(f"      host_pid1={host_pid} host_pid2={host_pid2} "
                      f"두 파이프 독립共存 (좀비 충돌 0)", flush=True)
            finally:
                # proc2 정리(QUIT).
                h = _wait_pipe(rf"\\.\pipe\imadhd-stdin-{host_pid2}", timeout=5)
                if h:
                    try: win32file.WriteFile(h, b"QUIT\n")
                    finally: win32file.CloseHandle(h)
                try: proc2.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc2.terminate(); proc2.wait(timeout=5)
        print("\n✅ PASS — pid 기반 파이프 end-to-end 검증 (slot 불일치 제거 확인)", flush=True)
        return 0
    except AssertionError as e:
        print(f"\n❌ FAIL — {e}", flush=True)
        return 1
    finally:
        # proc 정리.
        h = _wait_pipe(rf"\\.\pipe\imadhd-stdin-{host_pid}", timeout=3) if 'host_pid' in dir() else None
        if h:
            try: win32file.WriteFile(h, b"QUIT\n")
            except Exception: pass
            finally: win32file.CloseHandle(h)
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate(); proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
