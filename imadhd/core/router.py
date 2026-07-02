"""라우터 메인루프: 텔레그램 롱폴 → 명령 매칭 → 주입/회신.

확장: commands 리스트에 Command 추가하면 자동으로 새 명령 인식.
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
    from ..commands.inject_command import InjectCommand
    from ..commands.list_command import ListCommand

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tg = TelegramClient(settings.bot_token, settings.offset_path, settings.allowed_chat_id)
    reg = JSONFileRegistry(settings.registry_path, settings.max_slots)
    transport = SendKeysWinTransport()
    commands = [ListCommand(), InjectCommand()]
    ctx = CommandContext(settings=settings, registry=reg, transport=transport, telegram=tg)

    log.info("router start: slots=%d data_dir=%s", settings.max_slots, settings.data_dir)
    while True:
        try:
            updates = tg.get_updates(timeout=30)
        except Exception as e:
            log.warning("getUpdates failed: %s — retry in 5s", e)
            time.sleep(5)
            continue
        for upd in updates:
            m = upd.get("message") or upd.get("edited_message")
            if not m:
                continue
            chat = m.get("chat", {}).get("id")
            text = m.get("text", "") or ""
            if settings.allowed_chat_id and str(chat) != str(settings.allowed_chat_id):
                continue
            msg = Message(chat_id=str(chat), text=text, raw=upd)
            for cmd in commands:
                try:
                    if cmd.match(msg):
                        cmd.handle(msg, ctx)
                        break
                except Exception as e:
                    log.exception("command %s failed: %s", type(cmd).__name__, e)
