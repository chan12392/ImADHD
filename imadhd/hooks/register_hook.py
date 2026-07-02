"""SessionStart 훅: CC 세션 시작 → 빈 번호 할당 → HWND 캡처 → registry 등록.

stdin: CC hook payload JSON (session_id, cwd 등).
절차:
  1. session_id, cwd 확보
  2. registry 의 죽은 슬롯 sweep (IsWindow)
  3. 이 터미널 콘솔 창 HWND+PID 캡처 (GetConsoleWindow → GetWindowThreadProcessId)
  4. registry.claim_slot (동일 session_id 재사용 시 갱신)
  5. 신규/변경 시에만 텔레그램 알림 "✅ N번 터미널 연결됨"
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path


def _capture_terminal() -> tuple[int, int, dict]:
    """CC 터미널 창 HWND 와 CC PID(claude.exe) 반환 + 진단 정보.

    HWND: CC 터미널 창(주입/포커스용). 포그라운드 우선(detached 훅=콘솔없음).
    PID: **CC 프로세스(claude.exe)** pid — 부모체인에서 탐색.
        터미널 pid(WindowsTerminal) 가 아니라 CC pid 를 써야
        CC 종료를 정확히 감지(터미널 창은 탭 닫아도 안 죽음).

    반환: (hwnd, cc_pid, diag)
    """
    diag = {"foreground": 0, "console": 0, "fg_title": "", "chosen": "none",
            "cc_pid": 0, "terminal_pid": 0}
    hwnd = 0
    term_pid = 0
    try:
        import ctypes
        from ctypes import wintypes
        from ..core.proc_win import find_ancestor
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        fg = user32.GetForegroundWindow() or 0
        con = kernel32.GetConsoleWindow() or 0
        diag["foreground"] = int(fg)
        diag["console"] = int(con)
        if fg:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(fg, buf, 512)
            diag["fg_title"] = buf.value

        if fg:
            hwnd, diag["chosen"] = int(fg), "foreground"
        elif con:
            hwnd, diag["chosen"] = int(con), "console"
        else:
            hwnd = 0
        if hwnd:
            pid_box = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_box))
            term_pid = int(pid_box.value)
            diag["terminal_pid"] = term_pid

        # CC pid: 이 훅 프로세스(os.getpid()) 부터 부모체인에서 claude.exe 탐색.
        cc_pid = find_ancestor(os.getpid(), "claude") or 0
        diag["cc_pid"] = cc_pid
        # CC pid 못 잡으면 폴백 터미널 pid(구동작 호환).
        pid_out = cc_pid or term_pid or os.getpid()
        return hwnd, pid_out, diag
    except Exception as e:
        diag["error"] = repr(e)
        return 0, os.getpid(), diag


def _debug_log(line: str) -> None:
    """~/.imadhd/debug.log 에 진단 라인 추가. 설치 문제 실측용."""
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass



def _last_assistant_text(transcript_path: str) -> str:
    """transcript JSONL 의 마지막 assistant 텍스트 반환."""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    last = ""
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        msg = e.get("message") or e
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        txt = content if isinstance(content, str) else ""
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            txt = "\n".join(parts)
        if txt.strip():
            last = txt
    return last


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = payload.get("session_id", "") or ""
    cwd = payload.get("cwd", "") or os.getcwd()

    hwnd, pid, diag = _capture_terminal()
    started = datetime.datetime.now().isoformat(timespec="seconds")
    _debug_log(f"[register] session={session_id[:8]} pid_self={os.getpid()} hwnd={hwnd} pid_cap={pid} diag={diag}")

    from ..config import Settings
    from ..core.registry import JSONFileRegistry
    from ..telegram_api.client import TelegramClient

    s = Settings.load()
    reg = JSONFileRegistry(s.registry_path, s.max_slots)

    # 죽은 슬롯 정리: CC pid(claude.exe) 없으면 release (고아 슬롯 누적 방지).
    # pid 가 CC pid 이므로 CC 종료 시 정확 감지(터미널 pid 였던 구버그 수정).
    try:
        from ..core.proc_win import exists as _proc_exists
        import ctypes
        user32 = ctypes.windll.user32

        def _alive(info):
            if _proc_exists(info.pid):
                return True
            # CC pid 모르는(구) 슬롯: hwnd 라도 죽었으면 정리.
            return bool(info.hwnd and user32.IsWindow(info.hwnd))

        removed = reg.sweep_dead(_alive)
        if removed:
            _debug_log(f"[register] sweep removed {removed} dead slots")
    except Exception as e:
        _debug_log(f"[register] sweep error: {e!r}")

    # 중복 알림 방지: 동일 session_id + 동일 HWND+PID 면 이미 알림된 상태
    existing = reg.find_by_session(session_id)
    is_refresh = bool(
        existing
        and existing.hwnd == hwnd
        and existing.pid == pid
    )

    num = reg.claim_slot(session_id, hwnd, pid, cwd, started)
    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)

    if s.allowed_chat_id and not is_refresh:
        if num is None:
            tg.send(s.allowed_chat_id, f"⚠️ 모든 슬롯({s.max_slots}) 사용 중. 세션 미등록(PID {pid}).")
        else:
            tg.send(s.allowed_chat_id, f"✅ {num}번 터미널 연결됨 (PID {pid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
