"""Stop 훅: [A.D.H.D] 인입 turn 에서 CC 응답에 회신 마커 누락 시 차단.

inject_command 가 텔레그램 발신 메시지를 "{body} [A.D.H.D]" 형태로 터미널에
주입한다. CLAUDE.md 규칙상 CC 는 응답 마지막 줄에 같은 마커를 출력해야
reply_hook(Stop 훅)의 MarkerCapture 가 회신을 텔레그램으로 전송한다.
CC 가 이 마커를 깜빡하면 작업은 끝났는데 발신자에겐 아무 회신도 안 가는
silent failure 가 된다(2026-07-04 실사고: registry 버그 조사+수정+커밋까지
다 끝냈지만 마커 누락으로 텔레그램엔 응답 자체가 안 감).

channel-reply-guard.py(텔레그램/디스코드 plugin reply 도구 누락 차단)와
동일 패턴의 imadhd 버전 — 도구 호출 대신 "응답 마지막 줄 마커" 를 검사한다.

stop_hook_active=True(이미 한 번 block) 면 통과 — 무한루프 방지.
실패 시 조용히 통과(가드가 세션을 막아선 안 됨).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def get_role(entry: dict) -> str | None:
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("role")
    return entry.get("role") if isinstance(entry, dict) else None


def get_content(entry: dict):
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("content")
    return entry.get("content") if isinstance(entry, dict) else None


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def is_external_user_message(entry: dict) -> bool:
    """tool_result 만 있는 user round(API 왕복)는 실제 사용자 발화가 아니므로 제외."""
    if get_role(entry) != "user":
        return False
    content = get_content(entry)
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") in ("text", "image")
            for b in content
        )
    return False


def last_user_text(entries: list) -> str:
    for entry in reversed(entries):
        if is_external_user_message(entry):
            return extract_text(get_content(entry))
    return ""


def last_assistant_text(entries: list) -> str:
    for entry in reversed(entries):
        if get_role(entry) == "assistant":
            return extract_text(get_content(entry))
    return ""


def last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line
    return ""


def marker_missing(user_text: str, assistant_text: str, marker: str) -> bool:
    """마지막 user 발화에 마커가 있는데(=텔레그램 인입) 마지막 assistant
    응답의 마지막 줄에 마커가 없으면 True(=차단 대상)."""
    if marker not in user_text:
        return False  # 텔레그램 인입 turn 아님 — 일반 터미널 작업, 강제 X
    return marker not in last_nonempty_line(assistant_text)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        return 0

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0
    p = Path(transcript_path)
    if not p.exists():
        return 0

    entries = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return 0

    from ..config import Settings
    marker = Settings.load().reply_marker

    u_text = last_user_text(entries)
    a_text = last_assistant_text(entries)

    if not marker_missing(u_text, a_text, marker):
        return 0

    reason = (
        f"[imadhd marker-guard] {marker} 인입 turn인데 응답 마지막 줄에 "
        f"{marker} 없음 → 텔레그램 회신 안 감(reply_hook 마커 없으면 전송 skip). "
        f"응답 마지막 줄에 {marker} 다시 출력."
    )
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
