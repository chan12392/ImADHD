"""/use 명령: 고정 타겟(sticky) 설정/해제.

/use N   → 이후 번호 없는 본문을 N번 터미널로 자동 주입 (보드 🎯 표시)
/use off → 고정 타겟 해제

우선순위(router): 명시번호(/N·이모지) > reply_to 답장 > sticky > pending > auto.
즉 sticky 걸어도 "3 명령" 이나 답장이면 그쪽이 우선. 슬롯 사망 시 자동 해제.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext, normalize_command, resolve_active_slot
from ..core import slot_picker
from ..core import sticky as sticky_store


class UseCommand(Command):
    TRIGGERS = {"/use", "/고정", "/타겟"}

    def match(self, msg: Message) -> bool:
        t = normalize_command(msg.text)
        if not t:
            return False
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        chat = str(msg.chat_id)
        body = normalize_command(msg.text)
        parts = body.split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # 해제: off / 해제 / 취소 / 0
        if arg.lower() in {"off", "해제", "취소", "0", "none"}:
            if chat in ctx.sticky:
                del ctx.sticky[chat]
                sticky_store.save(ctx.settings.data_dir, ctx.sticky)
            ctx.telegram.send(msg.chat_id, "🎯 고정 타겟 해제")
            return

        # /use 단독 → slot 팝업(0=안내, 1=즉시고정, 2+=선택 대기).
        if not arg:
            picked = slot_picker.send_picker(
                ctx.telegram, msg.chat_id, "use", ctx.registry,
                (ctx.sticky or {}).get(chat))
            if picked is not None:
                slot_picker.rerun_with_slot(self, msg, ctx, "use", picked)
            return

        # 숫자 아닌 비-off 인자 → 사용법 안내
        if not arg.lstrip("-").isdigit():
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

        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음/종료",
            dead_message=f"❌ {num}번 터미널 없음/종료",
        )
        if not info:
            return

        ctx.sticky[chat] = num
        sticky_store.save(ctx.settings.data_dir, ctx.sticky)
        ctx.telegram.send(msg.chat_id, f"🎯 {num}번 터미널 고정 (본문 → 자동 주입)")
