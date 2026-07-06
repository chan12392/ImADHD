"""/label N <이름>: N번 터미널 표시 이름 지정. /list 에 표시.

WT 비활성 탭 이름은 Win32 API 로 못 얻어(활성탭만), 사용자가 직접 의미있는
이름을 붙임. 이름 생략(/label N) 시 라벨 삭제 → 기본(시간+status) 폴백.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext, normalize_command, resolve_active_slot


class LabelCommand(Command):
    TRIGGERS = ("/label", "/라벨", "/이름")

    def match(self, msg: Message) -> bool:
        t = normalize_command(msg.text)
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = normalize_command(msg.text).split(maxsplit=2)
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            ctx.telegram.send(msg.chat_id, "사용법: /label <N> <이름>  (이름 생략=삭제)")
            return
        num = int(parts[1])
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            check_alive=False,
        )
        if not info:
            return
        label = parts[2].strip() if len(parts) >= 3 else ""
        ok = ctx.registry.set_label(num, label)
        if not ok:
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 라벨 설정 실패")
            return
        if label:
            ctx.telegram.send(msg.chat_id, f"🏷️ {num}번 라벨: {label}")
        else:
            ctx.telegram.send(msg.chat_id, f"🏷️ {num}번 라벨 삭제")
