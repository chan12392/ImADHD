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
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


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


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FILETIME),
                                     ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                     ctypes.POINTER(_FILETIME)]
_EPOCH_DIFF = 11644473600  # 1601-01-01 → 1970 (초)

# console 재탐색용(AttachConsole→GetConsoleWindow). hwnd stale 복구.
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.GetConsoleWindow.argtypes = []
kernel32.FreeConsole.restype = wintypes.BOOL
kernel32.FreeConsole.argtypes = []
kernel32.AttachConsole.restype = wintypes.BOOL
kernel32.AttachConsole.argtypes = [wintypes.DWORD]

# PseudoConsole(ConPTY 가상창) → owner(진짜 터미널 창) 추적용.
user32 = ctypes.windll.user32
GW_OWNER = 4
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


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
