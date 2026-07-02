"""라우터 메인루프: 텔레그램 롱폴 → 명령 매칭 → 주입/회신.

매 폴링 전 감시(sweep): 죽은 터미널 슬롯 정리 + "❌ N번 종료" 알림 + 공지 갱신.
확장: commands 리스트에 Command 추가하면 자동 인식.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger("imadhd")


def run(settings: "Settings") -> None:
    from ..telegram_api.client import TelegramClient
    from .registry import JSONFileRegistry
    from ..transports.sendkeys_win import SendKeysWinTransport
    from ..commands.base import Message, CommandContext
    from ..commands.inject_command import (
        InjectCommand, do_inject, parse_leading_number, PENDING_TTL,
    )
    from ..commands.list_command import ListCommand
    from ..commands.pin_command import PinCommand
    from ..boards.pin_board import PinBoard

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tg = TelegramClient(settings.bot_token, settings.offset_path, settings.allowed_chat_id)
    reg = JSONFileRegistry(settings.registry_path, settings.max_slots)
    transport = SendKeysWinTransport()
    board = PinBoard(tg, reg, settings.allowed_chat_id, settings.data_dir, settings.max_slots)
    commands = [PinCommand(board), ListCommand(), InjectCommand()]
    ctx = CommandContext(settings=settings, registry=reg, transport=transport, telegram=tg)

    alive_fn = lambda info: transport.is_alive(info.to_dict())  # noqa: E731

    log.info("router start: slots=%d data_dir=%s", settings.max_slots, settings.data_dir)
    try:
        board.refresh_if_changed()   # 시작 시 공지 동기화(있으면)
    except Exception as e:
        log.warning("init board refresh failed: %s", e)

    while True:
        # 감시: 죽은 슬롯 정리 + 종료 알림 + 공지 갱신
        try:
            before = {i.number for i in reg.active()}
            reg.sweep_dead(alive_fn)
            after = {i.number for i in reg.active()}
            for n in sorted(before - after):
                tg.send(settings.allowed_chat_id, f"❌ {n}번 터미널 종료")
            board.refresh_if_changed()
        except Exception as e:
            log.warning("sweep/board error: %s", e)

        # 텔레그램 롱폴
        try:
            updates = tg.get_updates(timeout=15)
        except Exception as e:
            log.warning("getUpdates failed: %s — retry in 5s", e)
            time.sleep(5)
            continue

        for upd in updates:
            # ReplyKeyboard 클릭 = 텍스트 메시지("1️⃣⭕")로 도착 → 아래 명령 루프 처리
            m = upd.get("message") or upd.get("edited_message")
            if not m:
                continue
            chat = m.get("chat", {}).get("id")
            text = m.get("text", "") or ""
            if settings.allowed_chat_id and str(chat) != str(settings.allowed_chat_id):
                continue
            msg = Message(chat_id=str(chat), text=text, raw=upd)
            handled = False
            # 선택모드 pending: 번호 없는 본문 → 대기 번호로 주입
            if text and parse_leading_number(text) is None:
                pend = ctx.pending.get(str(chat))
                if pend:
                    pnum, pts = pend
                    if time.time() - pts <= PENDING_TTL:
                        del ctx.pending[str(chat)]
                        try:
                            do_inject(ctx, pnum, text, str(chat))
                            board.refresh_if_changed()
                            handled = True
                        except Exception as e:
                            log.exception("pending inject failed: %s", e)
                    else:
                        del ctx.pending[str(chat)]  # 만료 → 일반 메시지로
            if not handled:
                for cmd in commands:
                    try:
                        if cmd.match(msg):
                            cmd.handle(msg, ctx)
                            board.refresh_if_changed()
                            break
                    except Exception as e:
                        log.exception("command %s failed: %s", type(cmd).__name__, e)
