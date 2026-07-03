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
    from ..transports import make_transport
    from ..commands.base import Message, CommandContext
    from ..commands.inject_command import (
        InjectCommand, do_inject, parse_leading_number, PENDING_TTL,
    )
    from ..commands.list_command import ListCommand
    from ..commands.pin_command import PinCommand
    from ..commands.new_command import NewCommand
    from ..commands.open_command import OpenCommand
    from ..commands.close_command import CloseCommand
    from ..commands.stop_command import StopCommand
    from ..commands.help_command import HelpCommand
    from ..boards.pin_board import PinBoard

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tg = TelegramClient(settings.bot_token, settings.offset_path, settings.allowed_chat_id)
    reg = JSONFileRegistry(settings.registry_path, settings.max_slots)
    transport = make_transport(settings.transport)
    board = PinBoard(tg, reg, settings.allowed_chat_id, settings.data_dir, settings.max_slots)
    # 매칭 순서 주의: InjectCommand(번호/슬래시N) 는 가장 관대 → 마지막.
    # /list /pin /new /open /close /stop /help 전용 핸들러가 먼저 매칭되도록 앞에 둠.
    commands = [
        PinCommand(board), ListCommand(), NewCommand(),
        OpenCommand(), CloseCommand(), StopCommand(),
        HelpCommand(), InjectCommand(),
    ]
    ctx = CommandContext(settings=settings, registry=reg, transport=transport, telegram=tg)

    alive_fn = lambda info: transport.is_alive(info.to_dict())  # noqa: E731

    def _handle_callback(cbq: dict) -> None:
        """AskUserQuestion 인라인 버튼 클릭(callback_query) → ask 기록에 답 기록.

        ask_hook(PreToolUse)가 기다리는 ask 기록을 찾아 items[item].answer 를
        채운다. 전원 답이면 status=answered(훅이 폴링으로 감지). 메시지는
        선택 표시로 edit + 버튼 제거(중복 클릭 방지).
        """
        from ..core import ask_manager
        cq = cbq.get("id", "")
        cbdata = cbq.get("data", "") or ""
        cmsg = cbq.get("message") or {}
        chat = cmsg.get("chat", {}).get("id")
        # 보안: allowed chat 만(fail-closed). 외부 채팅의 callback 무시.
        if not settings.allow_any_chat and str(chat) != str(settings.allowed_chat_id or ""):
            try:
                tg.answer_callback(cq, "⚠️ 허용되지 않은 채팅")
            except Exception:
                pass
            return
        parsed = ask_manager.parse_callback(cbdata)
        if not parsed:
            try:
                tg.answer_callback(cq, "⚠️ 알 수 없는 버튼")
            except Exception:
                pass
            return
        ask_id, item_index, opt_index = parsed
        record = ask_manager.load_record(settings.data_dir, ask_id)
        if not record:
            try:
                tg.answer_callback(cq, "⚠️ 만료된 질문")
            except Exception:
                pass
            return
        items = record.get("items", [])
        if item_index < 0 or item_index >= len(items):
            try:
                tg.answer_callback(cq, "⚠️ 잘못된 항목")
            except Exception:
                pass
            return
        it = items[item_index]
        opts = it.get("options", [])
        if opt_index < 0 or opt_index >= len(opts):
            try:
                tg.answer_callback(cq, "⚠️ 잘못된 옵션")
            except Exception:
                pass
            return
        # 이미 답한 항목(중복 클릭) → 현재 선택만 안내, 변경 없음.
        if it.get("answer") is not None:
            try:
                tg.answer_callback(cq, f"이미 선택: {it['answer']}")
            except Exception:
                pass
            return
        label = opts[opt_index].get("label", "")
        it["answer"] = label
        if ask_manager.all_answered(record):
            record["status"] = "answered"
        ask_manager.write_record(settings.data_dir, record)
        try:
            tg.answer_callback(cq, f"✅ {label}")
        except Exception:
            pass
        # 해당 메시지를 선택 표시로 edit + 버튼 제거(빈 inline_keyboard).
        message_id = it.get("message_id")
        if message_id:
            try:
                tg.edit_message_text(
                    str(chat), message_id,
                    f"✅ {it['question']}\n→ {label}",
                    reply_markup={"inline_keyboard": []},
                )
            except Exception as e:
                log.warning("ask edit_message failed: %s", e)

    def _pending_num() -> int | None:
        """현재 선택대기 번호(단일 채팅). None=대기 없음."""
        p = ctx.pending.get(str(settings.allowed_chat_id))
        return p[0] if p else None

    log.info("router start: slots=%d data_dir=%s", settings.max_slots, settings.data_dir)
    try:
        board.refresh_if_changed()   # 시작 시 공지 동기화(있으면)
    except Exception as e:
        log.warning("init board refresh failed: %s", e)

    while True:
        # 감시: 죽은 슬롯 정리 + 공지 갱신.
        # 종료 알림은 채팅이 지저분해져 생략(상태 보드/​핀 + /list 로 확인).
        try:
            reg.sweep_dead(alive_fn)
            board.refresh_if_changed(pending_num=_pending_num())
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
            # 인라인 버튼 클릭(AskUserQuestion 답변) = callback_query 로 도착.
            cbq = upd.get("callback_query")
            if cbq:
                try:
                    _handle_callback(cbq)
                except Exception as e:
                    log.exception("callback handling failed: %s", e)
                continue
            # ReplyKeyboard 클릭 = 텍스트 메시지("1️⃣⭕")로 도착 → 아래 명령 루프 처리
            m = upd.get("message") or upd.get("edited_message")
            if not m:
                continue
            chat = m.get("chat", {}).get("id")
            text = m.get("text", "") or ""
            # allow_any_chat(dev)면 통과, 아니면 allowed 화이트리스트 chat만.
            if not settings.allow_any_chat and str(chat) != str(settings.allowed_chat_id or ""):
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
                            board.refresh_if_changed(pending_num=None)   # 주입 완료 → 📝
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
                            board.refresh_if_changed(pending_num=_pending_num())
                            break
                    except Exception as e:
                        log.exception("command %s failed: %s", type(cmd).__name__, e)
