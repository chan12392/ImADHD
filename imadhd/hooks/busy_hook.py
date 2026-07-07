"""UserPromptSubmit 훅: CC가 사용자 입력을 받으면 즉시 busy(📝) 표시.

터미널에서 직접 타이핑해도(텔레그램 경유 아님) 즉시 busy.
대표님 요청: "터미널 작업중이면 텔레그램에 busy — 텔레그램 소통 없어도."

동작:
  - session_id 가 registry 에 등록된 슬롯이면 status="busy".
  - 미등록 슬롯이면 무시 (SessionStart 가 먼저 claim).
  - Stop 훅(reply_hook)이 마커 무관 status="idle" 로 복귀.

주의: 라우터 주입(텔레그램→CC) 경로에서도 UserPromptSubmit 발화 → 이미 busy 라
idempotent. stdout 출력 없음 (프롬프트 변형 금지).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _debug_log(line: str) -> None:
    """진단 로그(reply_hook 과 동일 포맷). busy_hook 은 실패 원인 추적이
    어려워 추가(2026-07-07 감사 P0 — 기존엔 진단 로그 전무)."""
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = payload.get("session_id", "") or ""
    if not session_id:
        return 0

    from ..config import Settings
    from ..core.registry import JSONFileRegistry

    # 설정 미구성/.env 깨짐 → 상태갱신만 스킵, 훅 자체는 죽지 않음.
    # UserPromptSubmit 훅이 죽으면 CC 입력 처리 자체가 불명확해진다
    # (reply_hook.py:276-280 동일 패턴 — 2026-07-07 감사 P0).
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[busy] Settings.load failed session={session_id[:8]} err={e!r}")
        return 0
    try:
        reg = JSONFileRegistry(s.registry_path, s.max_slots)
        if reg.find_by_session(session_id):
            reg.set_status_by_session(session_id, "busy")
    except Exception as e:
        _debug_log(f"[busy] registry update failed session={session_id[:8]} err={e!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
