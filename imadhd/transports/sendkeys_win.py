"""Windows ctypes 기반 send_keys transport.

입력 = SendInput KEYEVENTF_UNICODE (유니코드 직접 → 한글/특수문자 가능).
keybd_event/VkKeyScan 경로는 한글(IME 조합) VK 를 못 얻어 폐기.

Windows 전용. 타 OS 에서는 미임포트(ImportError) → config 에서 다른 transport 선택.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes  # noqa: F401  (일부 빌드에서 바인딩에 필요)

from .base import Transport, InjectResult

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_V = 0x56  # Ctrl+V 붙여넣기
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
WM_CHAR = 0x0102
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# 주입 방식 토글: "paste"(기본, 클립보드 붙여넣기 ~77x 빠름) | "type"(문자별 SendInput, 레거시)
# 롤백: IMADHD_INJECT_METHOD=type 설정 후 재시작 → 기존과 100% 동일.
import os as _os
_INJECT_METHOD = (_os.environ.get("IMADHD_INJECT_METHOD", "paste") or "paste").strip().lower()

# 클립보드 API argtypes
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
kernel32.GlobalUnlock.restype = wintypes.BOOL


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint


def _clipboard_read_text():
    """현재 클립보드 유니코드 텍스트 읽기 (백업용). 없으면 None."""
    if not user32.OpenClipboard(0):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return None
        try:
            return ctypes.cast(ptr, ctypes.c_wchar_p).value
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _clipboard_set_text(text: str) -> bool:
    """클립보드에 유니코드 텍스트 설정. 성공 True."""
    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        user32.CloseClipboard()


def _paste_clipboard(text: str) -> bool:
    """클립보드 붙여넣기 주입. 한 번에 전체 → _type_unicode 대비 ~77x 빠름.
    \n/\r 스페이스 치환(_type_unicode 와 동일 정책 — CC 터미널 \n=제출 방지).
    기존 클립보드 백업/복원. 실패 시 False → 호출자 type 폴백.
    """
    text = text.replace("\r", " ").replace("\n", " ")
    bak = _clipboard_read_text()
    try:
        if not _clipboard_set_text(text):
            return False
        # Ctrl+V (한 번에 전체 붙여넣기)
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)  # 붙여넣기 처리 대기
        # Enter (제출)
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
        return True
    finally:
        if bak is not None:
            try:
                _clipboard_set_text(bak)
            except Exception:
                pass
        else:
            # 백업이 없던 경우: 주입한 텍스트가 전역 클립보드에 잔류하면 안 됨.
            # Telegram 명령에 토큰/민감 지시가 섞일 수 있어 EmptyClipboard 로 비움.
            try:
                if user32.OpenClipboard(0):
                    try:
                        user32.EmptyClipboard()
                    finally:
                        user32.CloseClipboard()
            except Exception:
                pass


def _type_unicode(text: str) -> None:
    """각 문자 UNICODE SendInput 전송 (한글 포함). 끝에 Enter.
    \n/\r 은 CC 터미널에서 Enter(제출)로 작동 → 스페이스로 치환(분할 주입 방지).
    """
    text = text.replace("\r", " ").replace("\n", " ")
    for ch in text:
        scan = ord(ch)
        down = _INPUT()
        down.type = INPUT_KEYBOARD
        down.ki.wVk = 0
        down.ki.wScan = scan
        down.ki.dwFlags = KEYEVENTF_UNICODE
        up = _INPUT()
        up.type = INPUT_KEYBOARD
        up.ki.wVk = 0
        up.ki.wScan = scan
        up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        arr = (_INPUT * 2)(down, up)
        user32.SendInput(2, arr, ctypes.sizeof(_INPUT))
        time.sleep(0.01)
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def _diag_log(line: str) -> None:
    try:
        from pathlib import Path
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class SendKeysWinTransport(Transport):
    def is_alive(self, target: dict) -> bool:
        """CC 생사. pid 의 프로세스가 claude.exe 여야 alive.
        터미널 pid(WindowsTerminal) 로 등록된 레거시 슬롯 → 자동 유령 처리.
        hwnd-only(구버그) 회피."""
        pid = target.get("pid")
        hwnd = target.get("hwnd")
        if pid:
            from ..core.proc_win import name_of
            return name_of(pid) == "claude.exe"
        return bool(hwnd and user32.IsWindow(hwnd))

    def inject(self, target: dict, text: str, background: bool = False) -> InjectResult:
        hwnd = target.get("hwnd")
        pid = target.get("pid")
        rediscovered = None
        if not hwnd or not user32.IsWindow(hwnd):
            # hwnd 무효(stale): WT 창 재생성·재정렬, 또는 register fg 오캡처.
            # CC(pid)는 살아있으므로 console_hwnd(pid) 로 현재 보이는 WT 창을 재탐색
            # (ConPTY PseudoConsole → owner GW_OWNER → CASCADIA 창 자동 추적).
            if pid:
                from ..core.proc_win import console_hwnd
                new_hwnd = console_hwnd(pid)
                if new_hwnd and user32.IsWindow(new_hwnd):
                    hwnd = new_hwnd
                    rediscovered = new_hwnd
                    _diag_log(f"[rediscover] pid={pid} stale_hwnd={target.get('hwnd')} new_hwnd={new_hwnd}")
            if not hwnd or not user32.IsWindow(hwnd):
                return InjectResult(delivered=False, method="none",
                                    note="hwnd invalid/dead (console 재탐색 실패)")
        if background:
            if self._post_message(hwnd, text):
                return InjectResult(
                    delivered=True, method="postmessage-bg",
                    note="best-effort; 도달 미보장(Windows Terminal 자식창엔 안 닿을 수 있음)",
                    rediscovered_hwnd=rediscovered,
                )
        focus_ok = self._focus_type(hwnd, text)
        if not focus_ok:
            # 포커스 탈취 실패해도 텍스트는 이미 타이핑됐다 — 엉뚱한(이전 활성) 창에
            # 들어갔을 수 있음. 조용히 성공 보고하면 대표님이 "왜 반응이 없지"로
            # 오인할 뿐 원인을 못 찾는다(2026-07-04 발견). delivered=False 로 표시.
            return InjectResult(delivered=False, method="focus",
                                note="포커스 확보 실패 — 다른 창에 입력됐을 수 있음",
                                rediscovered_hwnd=rediscovered)
        return InjectResult(delivered=True, method="focus", note="포커스 강제 입력",
                            rediscovered_hwnd=rediscovered)

    def send_key(self, target: dict, vk: int) -> InjectResult:
        """가상키 1개(ESC 등) 전송. /stop(작업 중단)용. 주입과 동일 포커스 확보 후
        keybd_event keydown/keyup."""
        hwnd = target.get("hwnd")
        pid = target.get("pid")
        rediscovered = None
        if not hwnd or not user32.IsWindow(hwnd):
            if pid:
                from ..core.proc_win import console_hwnd
                new_hwnd = console_hwnd(pid)
                if new_hwnd and user32.IsWindow(new_hwnd):
                    hwnd = new_hwnd
                    rediscovered = new_hwnd
            if not hwnd or not user32.IsWindow(hwnd):
                return InjectResult(delivered=False, method="none",
                                    note="hwnd invalid/dead (console 재탐색 실패)")
        focus_ok = self._acquire_focus(hwnd)
        user32.keybd_event(int(vk), 0, 0, 0)
        user32.keybd_event(int(vk), 0, KEYEVENTF_KEYUP, 0)
        if not focus_ok:
            return InjectResult(delivered=False, method="focus-vk",
                                note=f"포커스 확보 실패(vk=0x{vk:02X}) — 다른 창에 전달됐을 수 있음",
                                rediscovered_hwnd=rediscovered)
        return InjectResult(delivered=True, method="focus-vk", note=f"vk=0x{vk:02X}",
                            rediscovered_hwnd=rediscovered)

    def _post_message(self, hwnd, text: str) -> bool:
        """베타: WM_CHAR 로 백그라운드 전송 시도. 도달 여부는 반환 안 함 → 미보장."""
        try:
            for ch in text:
                user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
                time.sleep(0.01)
            user32.PostMessageW(hwnd, WM_CHAR, VK_RETURN, 0)
            return True
        except Exception:
            return False

    def _focus_type(self, hwnd, text: str) -> bool:
        focus_ok = self._acquire_focus(hwnd)
        if _INJECT_METHOD == "type":
            _type_unicode(text)
        else:
            # paste(클립보드 붙여넣기, 기본) — 실패 시 type 으로 폴백
            if not _paste_clipboard(text):
                _diag_log(f"[paste-fail] hwnd={hwnd} len={len(text)} fallback=_type_unicode")
                _type_unicode(text)
        return focus_ok

    def _acquire_focus(self, hwnd) -> bool:
        """hwnd 포커스 강제 확보. 텍스트 주입/가상키 전송 공통 선행.
        반환=실제 전경창이 hwnd 로 바뀌었는지(after_fg == hwnd) — SetForegroundWindow
        의 반환값 자체는 항상 정확하지 않아 GetForegroundWindow 재확인이 더 신뢰도 높음."""
        kernel32 = ctypes.windll.kernel32
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # 포커스락 타임아웃 0 → 백그라운드 프로세스도 SetForegroundWindow 허용
        SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
        try:
            user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, None, 0)
        except Exception:
            pass
        # 백그라운드 프로세스(router) 포커스 권한 획득: 현재 FG 스레드에 attach
        fg_now = user32.GetForegroundWindow() or 0
        tid_fg = user32.GetWindowThreadProcessId(fg_now, None) if fg_now else 0
        tid_self = kernel32.GetCurrentThreadId()
        attached = False
        if tid_fg and tid_fg != tid_self:
            attached = bool(user32.AttachThreadInput(tid_self, tid_fg, True))
        try:
            # Alt 키 흉내 → 사용자 입력으로 간주 → SetForegroundWindow 권한 획득
            user32.keybd_event(0x12, 0, 0, 0)        # Alt down
            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)  # Alt up
            ok = user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.4)
            after_fg = user32.GetForegroundWindow() or 0
            matched = after_fg == hwnd
            _diag_log(f"focus hwnd={hwnd} SetFG={ok} attached={attached} fg_before={fg_now} fg_after={after_fg} match={matched}")
            return matched
        finally:
            if attached:
                user32.AttachThreadInput(tid_self, tid_fg, False)
