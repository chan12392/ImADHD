"""/close N 명령: N번 터미널 종료 (CC 프로세스 + WT 탭).

대표님 2026-07-07: 슬롯만 해제(터미널 살림) → 터미널까지 닫기로 변경.
WT 단일 프로세스+다중 탭이라 WM_CLOSE 로 특정 탭 못 닫음 → host_pid(PTY-bridge)
트리 kill(taskkill /T /F) → CC 연쇄 종료 → WT 빈 탭 자동 닫힘.
비Windows(tmux): pane → session name → kill-session.
"""
from __future__ import annotations

import os
import subprocess

from .base import Command, Message, CommandContext, normalize_command, resolve_active_slot
from ..core import slot_picker
from ..core.proc_win import terminate_tree, find_tab_root


class CloseCommand(Command):
    TRIGGERS = ("/close", "/닫기", "/kill")

    def match(self, msg: Message) -> bool:
        t = normalize_command(msg.text)
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = normalize_command(msg.text).split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            # 인자 없음 → 활성 슬롯 인라인 팝업(0=안내, 1=즉시실행, 2+=선택 대기).
            sticky_num = (ctx.sticky or {}).get(msg.chat_id)
            picked = slot_picker.send_picker(
                ctx.telegram, msg.chat_id, "close", ctx.registry, sticky_num)
            if picked is not None:
                slot_picker.rerun_with_slot(self, msg, ctx, "close", picked)
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

        # 종료 (대표님 2026-07-07): WT 탭 루트(cmd.exe 등, WT 직전 자식) 우선 kill.
        # terminate_tree(tab_root) = 탭 전체 트리(shell→host→CC) 연쇄 종료 → WT 가
        # 루트 종료 감지하여 탭 닫음. host_pid 만 kill 시 탭 부모 shell 잔존 → 빈 탭 됨.
        # find_tab_root 못 찾으면(비WT/체인 이상) host_pid → pid 폴백(기존 동작).
        fallback_pid = getattr(info, "host_pid", 0) or info.pid
        killed = False
        if os.name == "nt":
            kill_target = find_tab_root(info.pid) or fallback_pid
            killed = terminate_tree(kill_target)
        elif os.name == "posix" and getattr(info, "tmux_pane", ""):
            try:
                r = subprocess.run(
                    ["tmux", "display-message", "-p", "-t", info.tmux_pane, "#S"],
                    capture_output=True, text=True, timeout=10,
                )
                sess = (r.stdout or "").strip()
                if sess:
                    subprocess.run(["tmux", "kill-session", "-t", sess], timeout=10)
                    killed = True
            except Exception:
                killed = False
        ctx.registry.release(num)
        if killed:
            ctx.telegram.send(msg.chat_id, f"🔒 {num}번 터미널 종료")
        else:
            ctx.telegram.send(
                msg.chat_id,
                f"⚠️ {num}번 프로세스 종료 실패 — 탭 직접 닫으세요 (슬롯은 해제됨)",
            )
