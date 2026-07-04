"""Stop 훅: CC 응답 종료 → transcript 마지막 assistant 답변 읽기 →
마커 감지 → 회신 (session_id→번호 역조회, 숫자이모지 붙여 전송).

인입(inject_command 가 주입한) 메시지엔 마커가 있는데 CC 응답 마지막 줄에
마커가 없으면(CLAUDE.md 규칙을 깜빡함) 조용히 통과하지 않고 Stop 을
block 해서 마커를 다시 출력하게 한다 — 작업은 끝났는데 회신만 안 가는
silent failure 방지(2026-07-04 실사고: 마커 누락으로 텔레그램 회신
자체가 안 감. channel-reply-guard.py 와 동일 패턴을 이 훅에 흡수해
별도 Stop 훅 프로세스를 추가하지 않음).

stdin: CC hook payload JSON (session_id, transcript_path, stop_hook_active).
stop_hook_active=True 면 통과(무한루프 방지).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _get_role(entry: dict) -> str | None:
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("role")
    return entry.get("role") if isinstance(entry, dict) else None


def _get_content(entry: dict):
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("content")
    return entry.get("content") if isinstance(entry, dict) else None


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def _is_external_user_message(entry: dict) -> bool:
    """tool_result 만 있는 user round(API 왕복)는 실제 사용자 발화가 아니므로 제외."""
    if _get_role(entry) != "user":
        return False
    content = _get_content(entry)
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") in ("text", "image")
            for b in content
        )
    return False


def last_user_text_from_entries(entries: list) -> str:
    for entry in reversed(entries):
        if _is_external_user_message(entry):
            return _extract_text(_get_content(entry))
    return ""


def _read_entries(transcript_path: str) -> list:
    p = Path(transcript_path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line
    return ""


def marker_missing(user_text: str, assistant_text: str, marker: str) -> bool:
    """마지막 user 발화에 마커가 있는데(=마커 인입 turn) 마지막 assistant
    응답의 마지막 줄에 마커가 없으면 True(=차단 대상)."""
    if marker not in user_text:
        return False  # 마커 인입 turn 아님 — 일반 터미널 작업, 강제 X
    return marker not in last_nonempty_line(assistant_text)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        return 0

    session_id = payload.get("session_id", "") or ""
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0

    from .register_hook import _last_assistant_text
    from ..config import Settings
    from ..core.registry import JSONFileRegistry
    from ..reply.marker_capture import MarkerCapture, ReplyPayload
    from ..reply.markup import md_to_tg_html
    from ..commands.inject_command import EMOJI_TO_NUM
    from ..telegram_api.client import TelegramClient

    # 설정 미구성/일시 오독(.env 등) → 회신·상태갱신만 스킵. Stop 자체는 막지 않음
    # (예외 미처리 시 훅이 죽어 idle 복귀도 회신도 안 되고 busy 로 영구 고정됨).
    try:
        s = Settings.load()
    except Exception:
        return 0
    text = _last_assistant_text(transcript_path)
    mc = MarkerCapture(s.reply_marker)
    rp = ReplyPayload(session_id, transcript_path, text)

    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    info = reg.find_by_session(session_id)
    emoji = ""
    if info:
        inv = {v: k for k, v in EMOJI_TO_NUM.items()}
        emoji = inv.get(info.number, f"[{info.number}]")
        reg.set_status_by_session(session_id, "idle")   # 작업 완료 → ⭕ 복귀 (마커 무관 — 터미널 직접 작업도 busy_hook 진입했으면 복귀)

    # 회신(텔레그램 전송)은 마커 있을 때만. idle 복귀는 위에서 마커 무관 처리.
    if not mc.should_reply(rp):
        entries = _read_entries(transcript_path)
        user_text = last_user_text_from_entries(entries)
        if marker_missing(user_text, text, s.reply_marker):
            reason = (
                f"[imadhd] {s.reply_marker} 인입 turn인데 응답 마지막 줄에 "
                f"{s.reply_marker} 없음 → 텔레그램 회신 안 감. "
                f"응답 마지막 줄에 {s.reply_marker} 다시 출력."
            )
            sys.stdout.write(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False) + "\n")
        return 0
    body = mc.build_text(rp)

    if not s.allowed_chat_id:
        return 0
    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)
    msg = f"{emoji} {body}".strip()
    # 마크다운 → Telegram HTML 렌더(코드블록/굵게/이탤릭). Markdown V1 은 코드펜스
    # 미지원 → 400 → plain 폴백 되는 문제 해결. HTML 모드 + md_to_tg_html 변환.
    # 변환/전송 실패 시 plain 폴백.
    try:
        tg.send(s.allowed_chat_id, md_to_tg_html(msg), parse_mode="HTML")
    except Exception:
        # plain 폴백도 실패하면(4096자 초과 외 사유) 여기서 죽지 않고 조용히 포기.
        # 이 예외를 못 잡으면 Stop 훅 자체가 죽어 idle 복귀는 됐어도 회신이
        # 통째로 유실된다(2026-07-04 발견).
        try:
            tg.send(s.allowed_chat_id, msg)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
