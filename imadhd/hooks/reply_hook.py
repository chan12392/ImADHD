"""Stop 훅: CC 응답 종료 → transcript 마지막 assistant 답변 읽기 →
마커 감지 → 회신 (session_id→번호 역조회, 숫자이모지 붙여 전송).

stdin: CC hook payload JSON (session_id, transcript_path, stop_hook_active).
stop_hook_active=True 면 통과(무한루프 방지).
"""
from __future__ import annotations

import json
import sys


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

    s = Settings.load()
    text = _last_assistant_text(transcript_path)
    mc = MarkerCapture(s.reply_marker)
    rp = ReplyPayload(session_id, transcript_path, text)
    if not mc.should_reply(rp):
        return 0
    body = mc.build_text(rp)

    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    info = reg.find_by_session(session_id)
    emoji = ""
    if info:
        inv = {v: k for k, v in EMOJI_TO_NUM.items()}
        emoji = inv.get(info.number, f"[{info.number}]")
        reg.set_status_by_session(session_id, "idle")   # 작업 완료 → ⭕ 복귀

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
        tg.send(s.allowed_chat_id, msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
