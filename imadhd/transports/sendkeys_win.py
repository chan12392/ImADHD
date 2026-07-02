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

VK_RETURN = 0x0D
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
WM_CHAR = 0x0102


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
        if not hwnd or not user32.IsWindow(hwnd):
            return InjectResult(delivered=False, method="none", note="hwnd invalid/dead")
        if background:
            if self._post_message(hwnd, text):
                return InjectResult(
                    delivered=True, method="postmessage-bg",
                    note="best-effort; 도달 미보장(Windows Terminal 자식창엔 안 닿을 수 있음)",
                )
        self._focus_type(hwnd, text)
        return InjectResult(delivered=True, method="focus", note="포커스 강제 입력")

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

    def _focus_type(self, hwnd, text: str) -> None:
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
            _diag_log(f"focus hwnd={hwnd} SetFG={ok} attached={attached} fg_before={fg_now} fg_after={after_fg} match={after_fg == hwnd}")
            _type_unicode(text)
        finally:
            if attached:
                user32.AttachThreadInput(tid_self, tid_fg, False)
