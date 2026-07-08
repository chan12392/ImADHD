"""/close 명령: 터미널 종료 (CC 프로세스 + WT 탭).

대표님 2026-07-07: 슬롯만 해제(터미널 살림) → 터미널까지 닫기로 변경.
WT 단일 프로세스+다중 탭이라 WM_CLOSE 로 특정 탭 못 닫음 → host_pid(PTY-bridge)
트리 kill(taskkill /T /F) → CC 연쇄 종료 → WT 빈 탭 자동 닫힘.
비Windows(tmux): pane → session name → kill-session.

대표님 2026-07-07 (인자 확장): 단일 N 외에 다중·전체 지원.
  /close N         단일
  /close N M ...   공백 다중
  /close N,M,...   콤마 다중 (띄어쓰기 혼합 OK: "1, 2, 3")
  /close all       활성 슬롯 전체 종료
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

    # ---------- 인자 파싱 ----------

    @staticmethod
    def _parse_targets(args: list[str]) -> tuple[bool, list[int] | None]:
        """args(parts[1:]) → (is_all, nums).

        - "all" 토큰 하나라도 → (True, [])  (nums 무시, 호출자가 active 로 채움)
        - 숫자 토큰들(콤마/공백 혼합 허용) → (False, [n, ...])  중복 제거·순서 보존
        - 숫자 아닌 토큰 섞임 / 빈 결과 → (False, None)  (사용법 안내)
        """
        if any(a.lower() == "all" for a in args):
            return True, []
        flat = " ".join(args).replace(",", " ").split()
        seen: set[int] = set()
        nums: list[int] = []
        for tok in flat:
            if tok.isdigit() and int(tok) > 0:
                n = int(tok)
                if n not in seen:
                    seen.add(n)
                    nums.append(n)
            else:
                return False, None   # 숫자 아님 → 잘못된 사용법
        if not nums:
            return False, None
        return False, nums

    # ---------- 단일 슬롯 종료 (메시지 송신 X, 상태만 반환) ----------

    @staticmethod
    def _terminate_one(ctx: CommandContext, num: int) -> str:
        """num 슬롯 종료 시도. 반환: 'killed' | 'fail' | 'missing'.

        단일 /close N 의 기존 동작과 동일(check_alive=False → 항상 kill 시도).
        메시지 송신은 호출자(handle)가 상태별 요약으로 일괄 송신.
        """
        info = ctx.registry.get(num)
        if not info:
            return "missing"
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
        return "killed" if killed else "fail"

    @staticmethod
    def _status_line(num: int, status: str) -> str:
        if status == "killed":
            return f"🔒 {num}번 터미널 종료"
        if status == "fail":
            return f"⚠️ {num}번 프로세스 종료 실패 — 탭 직접 닫으세요 (슬롯은 해제됨)"
        return f"❌ {num}번 터미널 없음"

    # ---------- handle ----------

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = normalize_command(msg.text).split()
        args = parts[1:]

        # 인자 없음 → 활성 슬롯 인라인 팝업(0=안내, 1=즉시실행, 2+=선택 대기).
        if not args:
            sticky_num = (ctx.sticky or {}).get(msg.chat_id)
            picked = slot_picker.send_picker(
                ctx.telegram, msg.chat_id, "close", ctx.registry, sticky_num)
            if picked is not None:
                slot_picker.rerun_with_slot(self, msg, ctx, "close", picked)
            return

        is_all, nums = self._parse_targets(args)
        if nums is None and not is_all:
            ctx.telegram.send(
                msg.chat_id,
                "❌ 사용법: /close N | /close N M … | /close N,M,… | /close all",
            )
            return

        if is_all:
            nums = [i.number for i in ctx.registry.active()]
            if not nums:
                ctx.telegram.send(msg.chat_id, "❌ 열린 터미널 없음")
                return

        # 단일 종료는 resolve_active_slot 경로를 그대로 유지(기존 동작·메시지 보존).
        if len(nums) == 1:
            self._close_single(msg, ctx, nums[0])
            return

        # 다중·전체: 슬롯별 종료 후 결과 한 건으로 요약(스팸 방지).
        killed: list[int] = []
        failed: list[int] = []
        missing: list[int] = []
        for n in nums:
            st = self._terminate_one(ctx, n)
            if st == "killed":
                killed.append(n)
            elif st == "fail":
                failed.append(n)
            else:
                missing.append(n)
        lines: list[str] = []
        if killed:
            lines.append(f"🔒 종료: {_fmt_nums(killed)}번")
        if failed:
            lines.append(f"⚠️ 종료 실패(슬롯은 해제): {_fmt_nums(failed)}번")
        if missing:
            lines.append(f"❌ 없음: {_fmt_nums(missing)}번")
        ctx.telegram.send(msg.chat_id, " / ".join(lines))

    def _close_single(self, msg: Message, ctx: CommandContext, num: int) -> None:
        """단일 종료 — 기존 resolve_active_slot 경로(동작·메시지 보존)."""
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            check_alive=False,
        )
        if not info:
            return
        status = self._terminate_one(ctx, num)
        ctx.telegram.send(msg.chat_id, self._status_line(num, status))


def _fmt_nums(nums: list[int]) -> str:
    """[1,2,3] → "1, 2, 3" (요약용)."""
    return ", ".join(str(n) for n in nums)
