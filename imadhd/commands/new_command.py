"""/new N 명령: N번 터미널에 /clear 주입 → 새 대화 시작.

 InjectCommand 의 일반 주입 경로와 동일하게 transport.inject 사용.
 단, 주입 텍스트 = "/clear" (CC 슬래시 명령). 마커 [A.D.H.D] 붙이지 않음 —
 /clear 는 회신이 필요 없는 CC 자체 명령이므로 Stop 훅 회신 트리거 불필요.
 주입 후 슬롯 상태 idle 로 환원.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext, normalize_command, resolve_active_slot
from ..core import slot_picker


class NewCommand(Command):
    TRIGGERS = ("/new", "/새대화", "/초기화")

    def match(self, msg: Message) -> bool:
        t = normalize_command(msg.text)
        return any(t == tr or t.startswith(tr + " ") for tr in self.TRIGGERS)

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        parts = normalize_command(msg.text).split()
        # /new 단독 → slot 팝업. /new N 만 허용(N 은 양의 정수).
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            sticky_num = (ctx.sticky or {}).get(msg.chat_id)
            picked = slot_picker.send_picker(
                ctx.telegram, msg.chat_id, "new", ctx.registry, sticky_num)
            if picked is not None:
                slot_picker.rerun_with_slot(self, msg, ctx, "new", picked)
            return
        num = int(parts[1])
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            dead_message=f"❌ {num}번 터미널 종료",
        )
        if not info:
            return
        ctx.transport.inject(info.to_dict(), "/clear")
        ctx.registry.set_status(num, "idle")
        ctx.telegram.send(msg.chat_id, f"♻️ {num}번 새 대화 시작 (/clear)")
