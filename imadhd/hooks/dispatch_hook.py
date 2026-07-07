"""PreToolUse 단일 디스패치 훅: stdin 1회 파싱 후 tool_name 으로 ask/perm 분기.

병합 배경(2026-07-07, 대표님 요구 "훅 너무 많다"):
  기존 PreToolUse 엔트리 2개
    - ask_hook  (matcher: AskUserQuestion)
    - perm_hook (matcher: Bash|Write|Edit)
  → 단일 엔트리(matcher: AskUserQuestion|Bash|Write|Edit)로 병합.
  총 훅 5→4. 기능 무손실 — 각 handle() 은 구버전 main() 본체와 동일 로직.

라우팅:
  tool_name == "AskUserQuestion"        → ask_hook.handle
  tool_name in {"Bash","Write","Edit"}  → perm_hook.handle
  그 외                                  → 미관여(exit 0, 출력 없음)

안전 도구(classify_risk 통과)·미구성(토큰/chat 없음)·터미널 직접 턴(마커 없음)은
각 handle 내부에서 출력 없이 exit 0 → CC 네이티벌/bypass 폴백 그대로 작동.

stdout 에는 JSON 만(CC 가 stdout 파싱). 진단은 ~/.imadhd/debug.log.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or ""
    if tool_name == "AskUserQuestion":
        # 함수 내 import: 미사용 경로(Write/Edit 등) 모듈 로드 비용 회피 + 훅
        # 호출 체인 최소화. ask/perm handle 은 서로 독립.
        from .ask_hook import handle as ask_handle
        return ask_handle(payload)
    if tool_name in ("Bash", "Write", "Edit"):
        from .perm_hook import handle as perm_handle
        return perm_handle(payload)
    # matcher 가 걸러주므로 원칙 도달 불가, 방어적으로 exit 0.
    return 0


if __name__ == "__main__":
    sys.exit(main())
