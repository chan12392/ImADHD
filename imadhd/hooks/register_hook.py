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


def main() -> int:
    raise NotImplementedError("implemented in plan step")
