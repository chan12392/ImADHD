"""ImADHD Windows PTY-bridge host (`py -m imadhd.host`).

WT(Windows Terminal) 창에서 `claude` 대신 이 스크립트로 세션을 시작한다:

    py -m imadhd.host -- claude
    py -m imadhd.host --slot 3 -- claude --resume

동작:
  - ConPTY(pywinpty 3.0.5) 위에서 자식(`claude` 기본)을 spawn 하고,
    호스트의 STDIN/STDOUT 을 PTY와 연결한다. 같은 WT 창 안에서
    자식의 TUI(claude 등)가 그대로 렌더링된다.
  - 라우터가 `\\\\.\\pipe\\imadhd-slot-<N>` 네임드파이프로 UTF-8 텍스트를
    주입하면(host 가 slot N 으로 서버 생성), `\n` 을 레코드 구분자로
    버퍼링해 읽은 뒤, 각 레코드를 `payload + "\r"` 로 바꿔 PTY에 쓴다.
    → 창 포커스 뺏기 없이 텔레그램 입력이 자식(claude)에 주입된다.
  - 사용자 키보드 입력은 같은 WT 창에서 계속 작동. 호스트가 STDIN을
    raw 콘솔 입력 모드(ENABLE_VIRTUAL_TERMINAL_INPUT)로 전환해
    Esc/방향키/Ctrl+C 등이 가로채지 않고 PTY 로 verbatim 전달된다.

slot 결정:
  - `--slot N` 우선. 없으면 register_hook 이 곧 claim 할 N을 미리 계산
    (Settings → registry sweep_dead → lowest_free). 동일 로직으로
    맞춰야 host 와 claude SessionStart 훅이 같은 N을 본다.
  - 결정된 N을 자식 env 의 `IMADHD_WANT_SLOT=str(N)` 으로 세팅 →
    register_hook 이 그 N을 강제로 claim.

인자: `py -m imadhd.host [--slot N] [--] [child args...]`
  child args 없으면 기본 `claude`.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

# ────────────────────────── Win32 constants ──────────────────────────

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11

ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PIPE_BUF = 4096
NAMED_PIPE_PREFIX = r"\\.\pipe\imadhd-stdin-"

DEFAULT_COLS = 120
DEFAULT_ROWS = 30

# pywin32 (named-pipe server). Optional at import time — `main()` errors out
# with a clear message if missing.
try:
    import win32file
    import win32pipe
    import pywintypes
    _HAS_PYWIN32 = True
except ImportError:  # pragma: no cover
    _HAS_PYWIN32 = False


# ────────────────────────── Win32 structs ──────────────────────────

class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class _CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", _COORD),
        ("dwCursorPosition", _COORD),
        ("wAttributes", ctypes.c_ushort),
        ("srWindow", _SMALL_RECT),
        ("dwMaximumWindowSize", _COORD),
    ]


def _kernel32():
    return ctypes.windll.kernel32


def _is_valid_handle(h) -> bool:
    return bool(h) and h != INVALID_HANDLE_VALUE and h != 0


def _host_log(msg: str) -> None:
    """PoC 진단용 로그. ~/.imadhd(라이브 상태) 말고 repo 루트에 쓴다."""
    try:
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "_host_diag.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ────────────────────────── Console size ──────────────────────────

def get_console_size() -> tuple[int, int]:
    """CONOUT$ 콘솔 크기(cols, rows) 반환. 실패 시 (120, 30)."""
    k32 = _kernel32()
    try:
        h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        if not _is_valid_handle(h):
            h = k32.CreateFileW(
                "CONOUT$",
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
        csbi = _CONSOLE_SCREEN_BUFFER_INFO()
        if not k32.GetConsoleScreenBufferInfo(h, ctypes.byref(csbi)):
            return DEFAULT_COLS, DEFAULT_ROWS
        cols = csbi.srWindow.Right - csbi.srWindow.Left + 1
        rows = csbi.srWindow.Bottom - csbi.srWindow.Top + 1
        if cols < 10 or rows < 2:
            return DEFAULT_COLS, DEFAULT_ROWS
        return int(cols), int(rows)
    except Exception:
        return DEFAULT_COLS, DEFAULT_ROWS


def enable_vt_output() -> None:
    """stdout 콘솔에 ANSI escape 가 해석되도록 VT_PROCESSING 켜기.
    리다이렉트(파이프)면 조용히 스킵."""
    try:
        k32 = _kernel32()
        h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        if not _is_valid_handle(h):
            return
        old = wintypes.DWORD()
        if not k32.GetConsoleMode(h, ctypes.byref(old)):
            return
        k32.SetConsoleMode(h, old.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


# ────────────────────────── Slot prediction ──────────────────────────

def predict_slot() -> int:
    """register_hook 이 곧 claim 할 N 을 미리 계산.

    register_hook 절차와 동일 결과를 내도록:
      1. Settings.load()
      2. JSONFileRegistry 생성 + sweep_dead(transport.is_alive)
      3. lowest_free(occupied, max_slots)
    host 시작 시점엔 session_id/pid 매칭이 없으므로 claim_slot 은
    항상 lowest_free 분기를 탄다 — 그러므로 host 도 동일하게 sweep 후
    lowest_free 를 계산한다.
    Settings/transport 사용 불가(테스트/미설정)면 기본 1.
    """
    try:
        from .config import Settings
        from .core.registry import JSONFileRegistry
        from .core.numberalloc import lowest_free
        from .transports import make_transport

        s = Settings.load()
        reg = JSONFileRegistry(s.registry_path, s.max_slots)
        try:
            transport = make_transport(s.transport)
            reg.sweep_dead(lambda info: transport.is_alive(info.to_dict()))
        except Exception:
            pass
        occupied = reg._occupied(reg._read())
        n = lowest_free(occupied, s.max_slots)
        return int(n) if n else 1
    except Exception:
        return 1


# ────────────────────────── Argv parsing ──────────────────────────

def parse_args(argv: list[str]) -> tuple[int | None, list[str]]:
    """`[--slot N] ... [--] [child args...]` → (slot|None, child_argv).

    기본 child_argv = ['claude'].
    """
    slot: int | None = None
    rest: list[str] = []
    i = 0
    seen_sep = False
    while i < len(argv):
        a = argv[i]
        if seen_sep:
            rest.append(a)
            i += 1
            continue
        if a == "--":
            seen_sep = True
            i += 1
            continue
        if a == "--slot":
            if i + 1 >= len(argv):
                raise SystemExit("host: --slot requires an integer argument")
            slot = int(argv[i + 1])
            i += 2
            continue
        if a.startswith("--slot="):
            slot = int(a.split("=", 1)[1])
            i += 1
            continue
        rest.append(a)
        i += 1
    if not rest:
        rest = ["claude"]
    return slot, rest


def _resolve_claude_exe(child_argv: list[str]) -> list[str] | None:
    """`claude` → npm 패키지 bin/claude.exe 직접 경로 해석.

    npm global shim(claude / claude.CMD / claude.ps1) 은 cmd.exe / sh 를 거쳐
    결국 `node_modules/@anthropic-ai/claude-code/bin/claude.exe` 를 exec 한다
    (실측 2026-07-06: claude.exe = 240MB 단일 바이너리, node 래핑 아님).
    이 shim 을 host PTY 직자식으로 spawn 하면 cmd.exe/sh 가 종료되며 PTY 가
    닫히고 → claude.exe 가 TTY 없이 고아화(2026-07-06 실사고: transcript
    한 줄도 안 써짐, host.py 즉시 exit code 1).

    회피: shim 을 역추적해 bin/claude.exe 를 **직접** PTY 자식으로 spawn.
    그러면 PTY 직자식 = claude.exe 그 자체 → 자식이 살아있는 한 PTY 안 닫힘.

    반환: [claude.exe경로, *rest]. 해석 실패(미설치/구조변경) → None.
    호출자는 None 시 기존 cmd.exe /c 폴백 유지(안전망).
    """
    if not child_argv:
        return None
    base = os.path.basename(child_argv[0]).lower()
    if base not in ("claude", "claude.exe"):
        return None
    # shim 위치 탐색(PATHEXT 자동). Windows 에선 보통 claude.CMD 잡힘.
    shim = None
    for cand in ("claude", "claude.cmd", "claude.bat", "claude.exe"):
        try:
            r = shutil.which(cand)
        except Exception:
            r = None
        if r:
            shim = r
            break
    if not shim:
        return None
    # shim dirname = npm global bin. 그 아래 표준 패키지 경로.
    exe = os.path.join(
        os.path.dirname(shim),
        "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe",
    )
    # LESSONLOOP(파싱 검증): 경로 실존 isfile 필수. 없으면 폴백 경로 위임.
    if os.path.isfile(exe):
        return [exe, *child_argv[1:]]
    return None


def _resolve_child(child_argv: list[str]) -> list[str]:
    """CreateProcessW 는 .cmd/.bat 을 직접 못 돌린다(claude.CMD 등 npm shim).
    우선 _resolve_claude_exe 로 bin/claude.exe 직접 해석 시도(PTY 고아화 방지).
    실패 시 shutil.which(PATH+PATHEXT 검색) 폴백:
      - .bat/.cmd → ['cmd.exe', '/c', resolved] + rest
      - .exe/.com → [resolved] + rest
      - 미해석(경로 이미 명시/없음) → 원본 그대로(spawn 에 위임)
    child_argv 가 비어있으면 (기본 ['claude']) 에도 동작.
    """
    if not child_argv:
        return ["claude"]
    # claude → bin/claude.exe 직접(PTY 직자식=claude.exe). 실패 시 아래 폴백.
    direct = _resolve_claude_exe(child_argv)
    if direct:
        return direct
    app = child_argv[0]
    # 이미 경로 포함 or 확장자 명시 → 그대로
    if (os.path.sep in app or (os.altsep and os.altsep in app)
            or app.lower().endswith((".exe", ".com", ".bat", ".cmd"))):
        return child_argv
    try:
        resolved = shutil.which(app)
    except Exception:
        resolved = None
    if not resolved:
        return child_argv
    low = resolved.lower()
    if low.endswith((".bat", ".cmd")):
        return ["cmd.exe", "/c", resolved, *child_argv[1:]]
    return [resolved, *child_argv[1:]]


def _build_env_string() -> str:
    """CreateProcessW env blob: 'KEY=VALUE\\0...\\0'. IMADHD_HOST_PID 주입.

    B-근본: 파이프 이름 imadhd-stdin-<host_pid>. host.py 자기 pid(os.getpid())를
    자식 CC env 에 주입 → register_hook 이 읽어 registry 에 저장 → router 가
    그 pid 로 파이프 주입. ppid 체인 불필요(CC 가 cmd→node→claude 다단계 자식).
    WANT_SLOT(slot 고정)은 폐지 — slot 은 register_hook 이 lowest_free 로 할당,
    host.py 는 slot 을 모름(불일치·좀비 경쟁 원인 제거).
    """
    env = dict(os.environ)
    env["IMADHD_HOST_PID"] = str(os.getpid())
    env.pop("IMADHD_WANT_SLOT", None)  # 상속 잔재 제거(불일치 방지).
    return "\0".join(f"{k}={v}" for k, v in env.items()) + "\0"


# ────────────────────────── Named-pipe server ──────────────────────────

def _make_pipe_instance(host_pid: int):
    name = f"{NAMED_PIPE_PREFIX}{host_pid}"
    handle = win32pipe.CreateNamedPipe(
        name,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        PIPE_BUF,
        PIPE_BUF,
        0,
        None,
    )
    return name, handle


def _write_record(pty, payload: bytes) -> None:
    """payload(UTF-8 bytes, '\\n' 미포함) → PTY 에 쓰고 엔터(\\r)로 제출.

    2026-07-07 fix: 긴 본문(이미지 경로+캡션 등) 주입 시 CC TUI 가 연속 입력을
    bracketed-paste 로 감지 → 끝 \\r 이 줄바꿈(제출 아님) 처리되는 현상 방지.
    text 와 \\r 분리 전송 + 사이 미세 sleep → \\r 이 paste 종료 후 단독 키로 도달
    = 제출(Enter) 로 인식. #38 shift+enter / #39 이미지 주입 동일 근본.
    단문은 영향 없음(sleep 0.08s 무시 가능). 부작용 = 주입 80ms 지연."""
    try:
        text = payload.decode("utf-8", "replace")
        if pty.isalive():
            pty.write(text)
            time.sleep(0.08)
            pty.write("\r")
    except Exception:
        pass


def pipe_server_loop(host_pid: int, pty, stop_event: threading.Event) -> None:
    """네임드파이프 서버 메인 루프.

    라우터는 inject 마다 open→write→close 한다(1회성 연결). 그래서 서버도
    1회 연결을 받아 처리한 뒤, 곧바로 다음 파이프 인스턴스를 만들고
    다음 연결을 기다린다(unlimited loop). stop_event 가 설정되면 즉시 종료.
    """
    while not stop_event.is_set():
        try:
            name, handle = _make_pipe_instance(host_pid)
        except Exception as e:
            _host_log(f"pipe create FAILED host_pid={host_pid} err={e!r}")
            return
        _host_log(f"pipe OK host_pid={host_pid} name={name} pre-connect")
        connected = False
        try:
            win32pipe.ConnectNamedPipe(handle, None)
            connected = True
            _host_log(f"pipe CONNECTED host_pid={host_pid} client arrived")
        except pywintypes.error as e:
            _host_log(f"pipe connect winerr host_pid={host_pid} winerror={e.winerror} str={e.strerror}")
        except Exception as e:
            _host_log(f"pipe connect UNCAUGHT host_pid={host_pid} type={type(e).__name__} err={e!r}")
        if not connected:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
            if stop_event.is_set():
                return
            continue
        buf = b""
        try:
            while True:
                try:
                    _, data = win32file.ReadFile(handle, PIPE_BUF)
                except pywintypes.error as e:
                    # 109 = ERROR_BROKEN_PIPE (client closed). 표준 종료 신호.
                    if e.winerror == 109:
                        break
                    raise
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    _write_record(pty, line)
            # 후행 '\n' 없이 클라이언트가 닫힌 경우: 남은 buf 도 한 레코드로 처리.
            if buf:
                _write_record(pty, buf)
        except Exception:
            pass
        finally:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass


# ────────────────────────── Keyboard forwarder ──────────────────────────

def _decode_console_input(data: bytes, cp: int) -> str:
    """콘솔 STDIN 바이트 → str. 콘솔 입력 CP(GetConsoleCP) 기반 디코딩.

    한국어 Windows 콘솔 입력 CP=949(기본). 예전 코드는 utf-8 하드코딩 →
    한글 바이트(CP949)를 UTF-8 로 오해석 → mojibake(영어 ASCII 는 CP 무관
    정상). CP 를 직접 읽어 맞춤: CP=65001(UTF-8) → utf-8, 그 외 → 'cp<N>'.
    알 수 없는 CP 코드 → utf-8 replace 폴백.
    """
    enc = "utf-8" if cp == 65001 else f"cp{cp}"
    try:
        return data.decode(enc, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def keyboard_loop(pty, stop_event: threading.Event) -> None:
    """호스트 STDIN(raw 모드) → PTY.

    STDIN이 콘솔이 아니면(리다이렉트/DEVNULL) 조용히 스킵 — 원시 모드를
    적용할 수 없고, 테스트/비인터랙티브 환경을 망가뜨리지 않기 위함.
    콘솔이면 ENABLE_VIRTUAL_TERMINAL_INPUT 만 켜서 Esc/방향키/Ctrl+C 가
    PTY 로 verbatim 전달되게 하고, finally에서 원래 모드로 복구.
    """
    k32 = _kernel32()
    try:
        h_in = k32.GetStdHandle(STD_INPUT_HANDLE)
        if not _is_valid_handle(h_in):
            return
        old_mode = wintypes.DWORD()
        if not k32.GetConsoleMode(h_in, ctypes.byref(old_mode)):
            return  # not a console (DEVNULL/파일) — 스킵
        # raw VT 입력: line/echo/processed 끄고 VT 입력만 켠다.
        if not k32.SetConsoleMode(h_in, ENABLE_VIRTUAL_TERMINAL_INPUT):
            return
        try:
            _host_log(f"kbd start CP={k32.GetConsoleCP()} OutCP={k32.GetConsoleOutputCP()} mode=VT_INPUT")
        except Exception:
            pass
    except Exception:
        return
    try:
        while not stop_event.is_set():
            try:
                _, data = win32file.ReadFile(h_in, 4096)
            except pywintypes.error:
                break
            if not data:
                break
            try:
                if any(b & 0x80 for b in data):
                    _host_log(f"kbd raw hex={data.hex()} len={len(data)} cp={k32.GetConsoleCP()}")
            except Exception:
                pass
            try:
                text = _decode_console_input(data, k32.GetConsoleCP())
                if pty.isalive():
                    pty.write(text)
            except Exception:
                pass
    finally:
        try:
            k32.SetConsoleMode(h_in, old_mode.value)
        except Exception:
            pass


# ────────────────────────── Output forwarder (main thread) ──────────────────────────

def output_loop(pty, stop_event: threading.Event) -> int:
    """PTY 출력 → 호스트 STDOUT. 자식 종료(iseof/!isalive) 감지 시 드레인 후 종료.

    반환값 = 자식 exit code.
    """
    out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    exit_code = 0
    while not stop_event.is_set():
        try:
            data = pty.read(blocking=False)
        except Exception:
            break
        if data:
            try:
                if isinstance(data, str):
                    out.write(data.encode("utf-8", "replace"))
                else:
                    out.write(data)
                out.flush()
            except Exception:
                pass
            continue
        # no data ready — 자식 종료 감지
        try:
            eof = pty.iseof()
        except Exception:
            eof = False
        try:
            alive = pty.isalive()
        except Exception:
            alive = False
        if eof or not alive:
            # 남은 버퍼 드레인
            time.sleep(0.05)
            for _ in range(10):
                try:
                    tail = pty.read(blocking=False)
                except Exception:
                    tail = ""
                if not tail:
                    break
                try:
                    if isinstance(tail, str):
                        out.write(tail.encode("utf-8", "replace"))
                    else:
                        out.write(tail)
                    out.flush()
                except Exception:
                    pass
            try:
                exit_code = pty.get_exitstatus() or 0
            except Exception:
                exit_code = 0
            break
        time.sleep(0.01)
    return int(exit_code or 0)


# ────────────────────────── main ──────────────────────────

def main() -> int:
    if not _HAS_PYWIN32:
        sys.stderr.write("host: pywin32 (win32pipe/win32file) required for named-pipe server\n")
        return 2

    slot_arg, child_argv = parse_args(sys.argv[1:])
    # claude → cmd.exe /c claude.CMD (CreateProcessW .cmd 직접실행 불가)
    child_argv = _resolve_child(child_argv)
    # B-근본: slot 인자/predict 폐지. 파이프 이름 = imadhd-stdin-<host_pid>.
    # slot 은 register_hook 이 lowest_free 로 할당(host.py 모름 → 불일치 제거).
    host_pid = os.getpid()

    cols, rows = get_console_size()

    try:
        import winpty
    except ImportError as e:
        sys.stderr.write(f"host: pywinpty required ({e!r})\n")
        return 2

    enable_vt_output()

    env_str = _build_env_string()
    # CC 작업 cwd 분리(2026-07-06): host.py 모듈 해석은 repo(py -m)지만
    # CC 자체는 IMADHD_CC_CWD 에서 시작. 미지정 시 host.py cwd 상속(레거시/테스트).
    # 목적: CC 가 홈 기반 프로젝트(C--Users-chan1) 로 인식 → resume 세션 목록 노출.
    cwd = os.environ.get("IMADHD_CC_CWD") or os.getcwd()

    pty = winpty.PTY(cols, rows)
    appname = child_argv[0]
    # CreateProcessW 스타일: cmdline 은 appname 뒤에 공백 + 인자 목록.
    # pywinpty.PTY.spawn 시그니처: spawn(appname, cmdline=None, ...).
    # cmdline=None 이면 appname 만 실행.
    cmdline_tail = None
    if len(child_argv) > 1:
        cmdline_tail = " " + subprocess.list2cmdline(child_argv[1:])
    try:
        ok = pty.spawn(appname, cmdline=cmdline_tail, cwd=cwd, env=env_str)
    except Exception as e:
        sys.stderr.write(f"host: spawn failed: {e!r}\n")
        return 2
    if not ok:
        sys.stderr.write("host: pty.spawn returned False\n")
        return 2

    _host_log(f"host start host_pid={host_pid} child={child_argv[:2]} spawned ok")

    stop_event = threading.Event()
    # pipe server thread — daemon: 프로세스 종료 시 같이 죽음(ConnectNamedPipe 블록 회피).
    threading.Thread(
        target=pipe_server_loop, args=(host_pid, pty, stop_event), daemon=True
    ).start()
    # keyboard thread — daemon: 자식 종료 후 프로세스 종료 시 같이 죽음.
    threading.Thread(
        target=keyboard_loop, args=(pty, stop_event), daemon=True
    ).start()

    try:
        exit_code = output_loop(pty, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
        try:
            pty.cancel_io()
        except Exception:
            pass
        return 130
    finally:
        stop_event.set()
        try:
            pty.cancel_io()
        except Exception:
            pass
    return int(exit_code or 0)


if __name__ == "__main__":
    sys.exit(main())
