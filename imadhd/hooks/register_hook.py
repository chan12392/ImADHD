"""SessionStart 훅: CC 세션 시작 → 빈 번호 할당 → HWND 캡처 → registry 등록.

stdin: CC hook payload JSON (session_id, cwd 등).
절차:
  1. session_id, cwd 확보
  2. registry 의 죽은 슬롯 sweep (IsWindow)
  3. 이 터미널 콘솔 창 HWND+PID 캡처 (GetConsoleWindow → GetWindowThreadProcessId)
  4. registry.claim_slot (동일 session_id 재사용 시 갱신)
  5. 연결 성공은 알림 없음(채팅 지저분해짐 방지, /list 로 확인). 슬롯 만실만 경고 알림.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path


def _capture_terminal() -> tuple[int, int, dict]:
    """CC 터미널 창 HWND 와 CC PID(claude.exe) 반환 + 진단 정보.

    HWND 우선순위 (2026-07-03 수정):
      1. **console_hwnd(cc_pid)** — CC pid 에서 결정론적으로 창 역추적
         (AttachConsole→GetConsoleWindow→PseudoConsole owner). 포그라운드
         레이스 무관, 세션마다 고유 핸들. 1 WT 창 다중탭이어도 CC본체 pid
         가 다르면 각기 다른 ConPTY owner hwnd 반환 → 정확 타겟.
      2. 폴백 GetForegroundWindow (레이스 위험, 마지막 수단)
      3. 폴백 GetConsoleWindow (detached 훅=보통 0)
    PID: **CC 프로세스(claude.exe)** pid — 부모체인에서 탐색.
        터미널 pid(WindowsTerminal) 가 아니라 CC pid 를 써야
        CC 종료를 정확히 감지(터미널 창은 탭 닫아도 안 죽음).

    반환: (hwnd, cc_pid, diag)
    """
    diag = {"foreground": 0, "console": 0, "console_hwnd": 0,
            "fg_title": "", "chosen": "none",
            "cc_pid": 0, "terminal_pid": 0}
    hwnd = 0
    term_pid = 0
    try:
        import ctypes
        from ctypes import wintypes
        from ..core.proc_win import find_ancestor, console_hwnd
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        # CC pid: 이 훅 프로세스(os.getpid()) 부터 부모체인에서 claude.exe 탐색.
        cc_pid = find_ancestor(os.getpid(), "claude") or 0
        diag["cc_pid"] = cc_pid

        # 1) pid 기반 결정론적 역추적 (1순위 — 포그라운드 레이스 무관).
        ch = console_hwnd(cc_pid) if cc_pid else 0
        diag["console_hwnd"] = int(ch or 0)
        if ch and user32.IsWindow(ch):
            hwnd, diag["chosen"] = int(ch), "console_hwnd"

        # 2/3) 폴백: 포그라운드 → 자기 콘솔.
        fg = user32.GetForegroundWindow() or 0
        con = kernel32.GetConsoleWindow() or 0
        diag["foreground"] = int(fg)
        diag["console"] = int(con)
        if fg:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(fg, buf, 512)
            diag["fg_title"] = buf.value
        if not hwnd:
            if fg:
                hwnd, diag["chosen"] = int(fg), "foreground"
            elif con:
                hwnd, diag["chosen"] = int(con), "console"

        if hwnd:
            pid_box = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_box))
            term_pid = int(pid_box.value)
            diag["terminal_pid"] = term_pid

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

    # 설정 미구성/일시 오독(.env 등) → 세션 등록만 스킵, CC 세션 시작은 막지 않음.
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[register] settings load failed: {e!r} — skip registration")
        return 0
    reg = JSONFileRegistry(s.registry_path, s.max_slots)

    # 죽은 슬롯 정리: transport.is_alive 로 판정(router 의 sweep 과 동일 로직 공유).
    # 과거엔 여기서 proc_win.exists(pid) 로 "존재만" 확인했는데, PID 재사용 시
    # exe 이름 검증 없이 다른 프로세스를 CC 로 오인할 수 있었다(router 쪽은
    # name_of(pid)=="claude.exe" 로 이미 더 엄격하게 판정 중이었음 — 두 판정기가
    # 서로 다른 기준으로 같은 슬롯을 흔드는 것을 방지하기 위해 통일).
    try:
        from ..transports import make_transport
        transport = make_transport(s.transport)

        def _alive(info):
            return transport.is_alive(info.to_dict())

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

    # 연결 성공 알림은 채팅이 지저분해져 생략(/list 로 언제든 확인 가능).
    # 슬롯 만실(실패)만 알림 — 실제 조치가 필요한 경우라 유지.
    if s.allowed_chat_id and not is_refresh and num is None:
        tg.send(s.allowed_chat_id, f"⚠️ 모든 슬롯({s.max_slots}) 사용 중. 세션 미등록(PID {pid}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
