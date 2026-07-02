"""Windows ctypes 기반 send_keys transport.

기존 send_keys_to_claude.py 로직 이식 + 확장:
  - HWND 직접 지정
  - --bg (백그라운드 PostMessage, 베타, 도달 보장 없음)
  - IsWindow 사전체크

Windows 전용. 타 OS 에서는 미임포트(ImportError) → config 에서 다른 transport 선택.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes  # noqa: F401  (일부 빌드에서 바인딩에 필요)

from .base import Transport, InjectResult

user32 = ctypes.windll.user32

VK_RETURN = 0x0D
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002
WM_CHAR = 0x0102


def _vk_and_shift(ch: str):
    vks = user32.VkKeyScanW(ord(ch))
    return vks & 0xFF, (vks >> 8) & 0x01


class SendKeysWinTransport(Transport):
    def is_alive(self, target: dict) -> bool:
        hwnd = target.get("hwnd")
        if not hwnd:
            return False
        return bool(user32.IsWindow(hwnd))

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
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        for ch in text:
            vk, shift = _vk_and_shift(ch)
            if shift:
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            if shift:
                user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
