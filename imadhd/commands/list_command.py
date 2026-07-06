"""/list (또는 /터미널) 명령: 현재 활성 세션 목록 텔레그램 전송.

표시: {번호이모지} #{N} {status} — {label > ai-title > 시작시간(HH:MM)}
  - status: 📝 작업중(busy) / ⭕ 대기(idle)
  - 이름 우선순위:
    1) /label N 이름 (수동 — 대표님이 부여, 최우선)
    2) ai-title (CC 가 현재 모델로 자동 생성한 세션 한 줄 요약)
    3) 시작시간 HH:MM (세션 시작 직후, ai-title 생성 전 폴백)
    WT 비활성 탭 이름은 Win32 API 로 못 얻음(활성탭만) → 위 3단계로 의미 있는 이름.
"""
from __future__ import annotations

import datetime

from .base import Command, Message, CommandContext, normalize_command
from .inject_command import EMOJI_TO_NUM
from ..core.transcript import read_ai_title


class ListCommand(Command):
    TRIGGERS = {"/list", "/터미널", "/terminals", "/세션"}

    def match(self, msg: Message) -> bool:
        return normalize_command(msg.text) in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        items = ctx.registry.active()
        if not items:
            ctx.telegram.send(msg.chat_id, "활성 터미널 없음")
            return
        inv = {v: k for k, v in EMOJI_TO_NUM.items()}
        lines = []
        for i in items:
            label = getattr(i, "label", "") or ""
            status = "📝" if getattr(i, "status", "") == "busy" else "⭕"
            if label:
                name = label
            else:
                ai = read_ai_title(
                    getattr(i, "session_id", ""), getattr(i, "cwd", "")
                )
                if ai:
                    name = ai
                else:
                    try:
                        name = datetime.datetime.fromisoformat(i.started_at).strftime("%H:%M")
                    except Exception:
                        name = "?"
            lines.append(f"{inv.get(i.number, '?')} #{i.number} {status} — {name}")
        ctx.telegram.send(msg.chat_id, "\n".join(lines))
