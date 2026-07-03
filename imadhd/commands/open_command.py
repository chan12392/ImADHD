"""/open 명령: 클로드 터미널 1개 새로 생성 (WT 신규 창 + claude).

`wt -w new new-tab --title Claude cmd /c claude` 를 detached 로 spawn.
SessionStart 훅(btg-register)이 새 CC 세션을 잡아 자동 번호 할당 →
"✅ N번 연결됨" 알림이 이어서 옴(무음).

claude = npm 글로벌(claude.cmd) → cmd /c 로 실행(.cmd 셸 필요).
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Command, Message, CommandContext

_DETACHED = 0x08
_NEW_PROC_GROUP = 0x200


def _wt_path() -> str:
    """wt.exe 경로. PATH → LOCALAPPDATA fallback(공개 툴 호환)."""
    return (
        shutil.which("wt.exe")
        or os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
                        "Microsoft", "WindowsApps", "wt.exe")
    )


class OpenCommand(Command):
    TRIGGERS = ("/open", "/새터미널", "/추가", "/new-term")

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip().lower() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        try:
            subprocess.Popen(
                [_wt_path(), "-w", "new", "new-tab", "--title", "Claude",
                 "cmd.exe", "/c", "claude"],
                creationflags=_DETACHED | _NEW_PROC_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
            return
        ctx.telegram.send(msg.chat_id, "🆕 새 터미널 생성 중… (수 초 내 번호 할당)")
