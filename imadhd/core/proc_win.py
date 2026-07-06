"""Windows 프로세스 도구. 의존성 0 (ctypes 자급자족).

- snapshot(): {pid: (exe_name_lower, parent_pid)}
- find_ancestor(start_pid, name): 부모체인 타고 올라가며 name(claude 등) 찾기 → pid
- exists(pid): 프로세스 생존 확인 (CC 생사 판별용 — 터미널 pid 아닌 CC pid 로 호출)

왜 필요: registry 가 터미널 pid(WindowsTerminal) 가 아니라 CC pid(claude.exe) 를 가져야
CC 종료를 정확히 감지. Windows Terminal 창 하나(한 pid) 에 탭 여러 CC 가 뜨므로
터미널 pid 로는 CC 단위 생사·구분 불가.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

_IS_WINDOWS = os.name == "nt"

# 비Windows(오라클/Linux tmux 등)에서 이 모듈을 top-level import 만 해도
# (예: commands/list_command.py) 죽지 않도록 ctypes.windll 접근을 전부
# Windows 전용 분기 안으로 격리. kernel32/user32 는 None → 아래 함수들은
# 각자 hwnd/pid=0 조기 반환으로 실제 호출을 회피(2026-07-05 실사고:
# 클로이 오라클 라우터가 이 import 하나로 전체 크래시).
kernel32 = None
user32 = None
GW_OWNER = 4

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_EPOCH_DIFF = 11644473600  # 1601-01-01 → 1970 (초)


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


if _IS_WINDOWS:
    kernel32 = ctypes.windll.kernel32

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FILETIME),
                                         ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                         ctypes.POINTER(_FILETIME)]

    # console 재탐색용(AttachConsole→GetConsoleWindow). hwnd stale 복구.
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    kernel32.GetConsoleWindow.argtypes = []
    kernel32.FreeConsole.restype = wintypes.BOOL
    kernel32.FreeConsole.argtypes = []
    kernel32.AttachConsole.restype = wintypes.BOOL
    kernel32.AttachConsole.argtypes = [wintypes.DWORD]

    # PseudoConsole(ConPTY 가상창) → owner(진짜 터미널 창) 추적용.
    user32 = ctypes.windll.user32
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL

    # sync_alive 자가치유용: pid → top-level 창 hwnd(터미널 창 역추적).
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]


def window_title(hwnd: int) -> str:
    """창 제목 반환. /list 표시용. 실패/빈칸→''."""
    try:
        hwnd = int(hwnd or 0)
        if not hwnd or not user32.IsWindow(hwnd):
            return ""
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def snapshot() -> dict[int, tuple[str, int]]:
    """전체 프로세스 스냅. 반환 {pid: (exe_name_lower, parent_pid)}."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out: dict[int, tuple[str, int]] = {}
    if not snap:
        return out
    try:
        pe = _PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                out[int(pe.th32ProcessID)] = (
                    (pe.szExeFile or "").lower(),
                    int(pe.th32ParentProcessID),
                )
                if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return out


def find_ancestor(start_pid: int, name: str) -> int | None:
    """start_pid 부터 부모체인 올라가며 exe==name(.exe 무관) 인 조상 pid 반환.

    name='claude' → 'claude.exe' 매칭. 못 찾으면 None.
    """
    target = name.lower().removesuffix(".exe") + ".exe"
    procs = snapshot()
    pid = int(start_pid or 0)
    seen: set[int] = set()
    while pid and pid not in seen:
        seen.add(pid)
        info = procs.get(pid)
        if not info:
            return None
        exe, ppid = info
        if exe == target:
            return pid
        pid = ppid
    return None


def exists(pid: int) -> bool:
    """pid 프로세스 생존 여부. CC pid 로 호출 → CC 종료 감지."""
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        # OpenProcess 실패 = 보통 없거나 권한없음. 없다고 간수(보수).
        procs = snapshot()
        return pid in procs
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == _STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(h)


def name_of(pid: int) -> str:
    """pid 의 exe 이름(소문자, .exe 포함). 없으면 ''."""
    return snapshot().get(int(pid), ("", 0))[0]


def console_hwnd(cc_pid: int) -> int:
    """cc_pid(claude.exe)가 붙은 콘솔 창 hwnd 반환. registry.hwnd 복구용.

    CC는 자체 창이 없고 부모 콘솔(powershell console)창에 붙어 있음.
    AttachConsole(cc_pid)로 그 콘솔에 연결 → GetConsoleWindow 로 보이는 창 hwnd 획득.
    registry.hwnd 는 터미널 창이 재생성되면 옛값(stale)이 되지만 CC(pid)는 살아있으므로,
    이 함수로 현재 창을 재발견. 실패 0.

    부작용: 호출 프로세스의 콘솔 연결 해제(FreeConsole). router(pm2 fork)는 콘솔 의존
    없으므로 무해. FreeConsole 은 호출 프로세스만 뗌 → CC 자체 입출력엔 영향 없음.

    한계: 한 콘솔에 CC 여러 개(터미널 탭)면 먼저 attach 한 콘솔 반환 → 부정확 가능.
    현재 구성(Stream Deck 이 콘솔 개별 런칭 = CC당 1콘솔)에선 문제 없음.
    """
    if not cc_pid:
        return 0
    try:
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(int(cc_pid)):
            return 0
        raw = int(kernel32.GetConsoleWindow() or 0)
    except Exception:
        return 0
    finally:
        try:
            kernel32.FreeConsole()
        except Exception:
            pass
    if not raw:
        return 0
    # ConPTY 가상창(PseudoConsoleWindow) → owner 가 진짜 WT/터미널 창.
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(raw, cls, 256)
    if cls.value == "PseudoConsoleWindow":
        owner = user32.GetWindow(raw, GW_OWNER) or 0
        return owner or raw
    return raw


def create_time(pid: int) -> float | None:
    """pid 프로세스 생성시각(unix epoch). 보정(시간순 매칭)용. 실패 시 None."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        ct = _FILETIME()
        dummy = (_FILETIME(), _FILETIME(), _FILETIME())
        if kernel32.GetProcessTimes(h, ctypes.byref(ct), *map(ctypes.byref, dummy)):
            val = (ct.dwHighDateTime << 32) | ct.dwLowDateTime
            return val / 1e7 - _EPOCH_DIFF
        return None
    finally:
        kernel32.CloseHandle(h)


def claude_pids() -> list[int]:
    """현재 살아있는 claude.exe pid 목록. sync_alive 자가치유용."""
    if not _IS_WINDOWS:
        return []
    try:
        snap = snapshot()
        return [pid for pid, (exe, _ppid) in snap.items() if exe == "claude.exe"]
    except Exception:
        return []


def find_recent_session_id() -> str | None:
    """~/.claude/projects/** 에서 가장 최근 mtime *.jsonl 의 stem(session_id) 반환.

    단일 활성 CC 가정(대표님 사용 패턴). SessionStart 훅이 안 돈 세션의
    session_id 를 sync_alive 가 유추용. 여러 CC 동시 활동이면 가장 최근 하나.
    없으면 None → 호출처가 auto-<pid> 폴백.
    """
    try:
        root = Path.home() / ".claude" / "projects"
        if not root.exists():
            return None
        latest: Path | None = None
        latest_mtime = -1.0
        for p in root.rglob("*.jsonl"):
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m > latest_mtime:
                latest_mtime = m
                latest = p
        return latest.stem if latest else None
    except Exception:
        return None


def _top_window_of_pid(target_pid: int) -> int:
    """해당 pid 의 보이는(타이틀 있는) top-level 창 hwnd. EnumWindows. 없으면 0."""
    if not target_pid or not _IS_WINDOWS:
        return 0
    try:
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        found: list[int] = []

        def _cb(hwnd: int, _l: int) -> bool:
            pid_box = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_box))
            if pid_box.value == target_pid and user32.IsWindowVisible(hwnd):
                if user32.GetWindowTextLengthW(hwnd) > 0:
                    found.append(hwnd)
                    return False  # 첫 창 발견 → 중지
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        return found[0] if found else 0
    except Exception:
        return 0


def find_terminal_hwnd(cc_pid: int) -> int:
    """cc_pid 부모체인의 터미널(WindowsTerminal/conhost/OpenConsole) top-level 창 hwnd.

    console_hwnd(AttachConsole→GetConsoleWindow 방식)의 폴백. CC 가 자체 콘솔을
    소유하지 않고 부모 터미널이 소유한 ConPTY 환경에서 console_hwnd 가 0 을
    반환할 때, 부모 터미널 pid 의 보이는 창을 직접 찾는다. 없으면 0.
    """
    if not cc_pid or not _IS_WINDOWS:
        return 0
    try:
        snap = snapshot()
        pid = int(cc_pid)
        seen: set[int] = set()
        while pid and pid not in seen:
            seen.add(pid)
            exe, ppid = snap.get(pid, ("", pid))
            if exe in ("windowsterminal.exe", "conhost.exe", "openconsole.exe"):
                h = _top_window_of_pid(pid)
                if h:
                    return h
            pid = ppid
    except Exception:
        return 0
    return 0
