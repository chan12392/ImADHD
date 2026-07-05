"""/use 명령: 고정 타겟(sticky) 설정/해제.

/use N   → 이후 번호 없는 본문을 N번 터미널로 자동 주입 (보드 🎯 표시)
/use off → 고정 타겟 해제

우선순위(router): 명시번호(/N·이모지) > reply_to 답장 > sticky > pending > auto.
즉 sticky 걸어도 "3 명령" 이나 답장이면 그쪽이 우선. 슬롯 사망 시 자동 해제.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext
from ..core import sticky as sticky_store


class UseCommand(Command):
    TRIGGERS = {"/use", "/고정", "/타겟"}

    def match(self, msg: Message) -> bool:
        t = (msg.text or "").strip().lower()
        if not t:
            return False
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        chat = str(msg.chat_id)
        body = (msg.text or "").strip()
        parts = body.split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # 해제: off / 해제 / 취소 / 0
        if arg.lower() in {"off", "해제", "취소", "0", "none"}:
            if chat in ctx.sticky:
                del ctx.sticky[chat]
                sticky_store.save(ctx.settings.data_dir, ctx.sticky)
            ctx.telegram.send(msg.chat_id, "🎯 고정 타겟 해제")
            return

        # 사용법 안내: 인자 없음 / 숫자 아님
        if not arg or not arg.lstrip("-").isdigit():
            ctx.telegram.send(
                msg.chat_id,
                "사용법: /use 3  → 3번 터미널 고정(본문 자동 주입)\n"
                "        /use off  → 해제",
            )
            return

        num = int(arg)
        max_slots = getattr(ctx.settings, "max_slots", 6)
        if not (1 <= num <= max_slots):
            ctx.telegram.send(msg.chat_id, f"❌ 1~{max_slots}번만 가능")
            return

        info = ctx.registry.get(num)
        if not info or not ctx.transport.is_alive(info.to_dict()):
            if info:
                ctx.registry.release(num)
            ctx.telegram.send(msg.chat_id, f"❌ {num}번 터미널 없음/종료")
            return

        ctx.sticky[chat] = num
        sticky_store.save(ctx.settings.data_dir, ctx.sticky)
        ctx.telegram.send(msg.chat_id, f"🎯 {num}번 터미널 고정 (본문 → 자동 주입)")
