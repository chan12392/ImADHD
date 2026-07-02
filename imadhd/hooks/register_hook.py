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
    """CC 터미널 창 HWND 와 소유 PID 반환 + 진단 정보.

    CC 가 훅을 detached 로 spawn → 훅에겐 콘솔 없음(GetConsoleWindow=0).
    따라서 포그라운드 우선: SessionStart 동기 실행 시 포그라운드=CC 터미널.
    폴백: GetConsoleWindow. 최후 os.getpid().
    반환: (hwnd, pid, diag)  diag={foreground, console, fg_title, chosen}
    """
    diag = {"foreground": 0, "console": 0, "fg_title": "", "chosen": "none"}
    try:
        import ctypes
        from ctypes import wintypes
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
            hwnd, diag["chosen"] = fg, "foreground"
        elif con:
            hwnd, diag["chosen"] = con, "console"
        else:
            return 0, os.getpid(), diag
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(hwnd), int(pid.value), diag
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

    # 죽은 슬롯 정리: IsWindow False → release (고아 슬롯 누적 방지)
    try:
        import ctypes
        user32 = ctypes.windll.user32
        removed = reg.sweep_dead(lambda info: bool(info.hwnd and user32.IsWindow(info.hwnd)))
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
