"""SessionStart 훅: CC 세션 시작 → 빈 번호 할당 → HWND 캡처 → registry 등록.

stdin: CC hook payload JSON (session_id, cwd 등).
절차:
  1. session_id, cwd 확보
  2. registry.claim_slot
  3. GetForegroundWindow() 로 HWND 캡처 (시작 직후 포커스=이 터미널)
  4. pid 기록
  5. 텔레그램 알림 "✅ N번 터미널 연결됨"
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path


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

    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
    except Exception:
        hwnd = 0

    pid = os.getpid()
    started = datetime.datetime.now().isoformat(timespec="seconds")

    from ..config import Settings
    from ..core.registry import JSONFileRegistry
    from ..telegram_api.client import TelegramClient

    s = Settings.load()
    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    num = reg.claim_slot(session_id, hwnd, pid, cwd, started)
    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)

    if s.allowed_chat_id:
        if num is None:
            tg.send(s.allowed_chat_id, f"⚠️ 모든 슬롯({s.max_slots}) 사용 중. 세션 미등록(PID {pid}).")
        else:
            tg.send(s.allowed_chat_id, f"✅ {num}번 터미널 연결됨 (PID {pid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
