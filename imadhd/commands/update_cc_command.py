"""/update 명령: 활성 CC 에 `!claude update` 주입.

대표님 지시: "`!claude update` 이렇게만 전송하면 될 거 같은데".
do_inject(inject_command) 재사용 — slot 해석 + alive 체크 + busy 표시 +
marker_pending(회신 대상 턴 플래그) 전부 포함.

slot 해석 우선순위 = pending → sticky → active 단일. active 0 또는 2+ → 안내.
(대표님 단일 CC 사용 패턴이므로 active 단일 auto-target 이 주경로.)

캐비어트: `claude update` 서브커맨드 silent-fail 리포트 존재(GitHub #5494).
대표님 지시대로 단순주입 유지. CC 시작 시 자동업데이트도 하므로 restart 만으로
충분한 경우 많음.
"""
from __future__ import annotations

from .base import Command, Message, CommandContext
from .inject_command import do_inject


class UpdateCcCommand(Command):
    TRIGGERS = {"/update", "/업데이트"}

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip().lower() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        tg = ctx.telegram
        chat = msg.chat_id
        reg = ctx.registry

        num = _resolve_slot(ctx, chat)
        if num is None:
            actives = reg.active()
            if not actives:
                tg.send(chat, "❌ 열린 CC 없음")
            else:
                tg.send(chat, f"❌ CC {len(actives)}개 — 번호로 지정(/update 대신 N️⃣ 또는 /N)")
            return

        do_inject(ctx, num, "!claude update", chat)
        tg.send(chat, f"🔄 CC 업데이트 주입 (!claude update → {num}번)")


def _resolve_slot(ctx: CommandContext, chat: str) -> int | None:
    """주입 대상 슬롯: pending → sticky → active 단일. 없으면 None."""
    pend = ctx.pending.get(chat)
    if pend:
        return pend[0]
    stick = ctx.sticky.get(chat)
    if stick is not None:
        try:
            return int(stick)
        except (TypeError, ValueError):
            return None
    actives = ctx.registry.active()
    if len(actives) == 1:
        return actives[0].number
    return None
