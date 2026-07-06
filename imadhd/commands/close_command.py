"""/close N 명령: N번 터미널 종료.

절차:
  1. WM_CLOSE 전송(WT 창 graceful 종료 요청)
  2. taskkill /F /PID <cc_pid> /T — CC 프로세스 트리 강제 종료(보측)
     cmd /c claude 구성이라 claude 사망 → cmd 종료 → WT 탭 closeOnExit 로 창 닫힘.
  3. registry 슬롯 release

1 CC = 1 WT 창 모델에서 창 전체 닫힘. WT 다중탭/확인대화상자 예외는 taskkill 이 보측.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

from .base import Command, Message, CommandContext, resolve_active_slot

WM_CLOSE = 0x0010
# 비Windows(오라클 tmux 등)에서 top-level import 만으로 죽지 않도록 격리.
# hwnd 는 그 플랫폼에서 항상 0 이라 handle() 의 `if info.hwnd:` 가 실사용을 막는다.
_user32 = None
if os.name == "nt":
    _user32 = ctypes.windll.user32
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL


class CloseCommand(Command):
    TRIGGERS = ("/close", "/닫기", "/kill")

    def match(self, msg: Message) -> bool:
        t = (msg.text or "").strip().lower()
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = (msg.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            ctx.telegram.send(msg.chat_id, "사용법: /close 1  → 1번 터미널 종료")
            return
        num = int(parts[1])
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            check_alive=False,
        )
        if not info:
            return

        if os.name == "nt":
            # 1) WM_CLOSE (WT 창 graceful)
            if info.hwnd:
                try:
                    _user32.PostMessageW(int(info.hwnd), WM_CLOSE, 0, 0)
                except Exception:
                    pass
            # 2) taskkill cc_pid 트리 (보측 — claude 강제 종료 → cmd/WT 연쇄 종료)
            if info.pid:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(info.pid), "/T"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
        else:
            pane = getattr(info, "tmux_pane", "")
            if pane:
                try:
                    r = subprocess.run(
                        ["tmux", "display-message", "-p", "-t", pane, "#S"],
                        capture_output=True, text=True, timeout=5,
                    )
                    session_name = (r.stdout or "").strip()
                    if session_name:
                        subprocess.run(["tmux", "kill-session", "-t", session_name], timeout=5)
                except Exception:
                    pass

        ctx.registry.release(num)
        ctx.telegram.send(msg.chat_id, f"🚪 {num}번 터미널 닫음")
