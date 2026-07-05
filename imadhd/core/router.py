"""라우터 메인루프: 텔레그램 롱폴 → 명령 매칭 → 주입/회신.

매 폴링 전 감시(sweep): 죽은 터미널 슬롯 정리 + "❌ N번 종료" 알림 + 공지 갱신.
확장: commands 리스트에 Command 추가하면 자동 인식.
"""
from __future__ import annotations

import logging
import time
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger("imadhd")


def classify_getupdates_error(exc: Exception) -> tuple[str, float]:
    """getUpdates 예외를 (action, wait_seconds) 로 분류.

    action="stop": 재시도해도 절대 해결 안 되는 실패(토큰 무효/봇 차단) —
    무한 재시도로 "죽었는데 살아있는 척"하며 조용히 멈추는 것보다(2026-07-04
    8시간 정지 사고와 같은 계열) 예외를 올려 프로세스를 종료시켜 pm2 재시작
    카운트로 이상 신호가 눈에 띄게 한다.
    action="wait": 그 외(네트워크 일시 오류, 429 등) — wait_seconds 만큼
    대기 후 재시도."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "stop", 0.0
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                return "wait", float(retry_after)
            except (TypeError, ValueError):
                return "wait", 5.0
    return "wait", 5.0


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
    from ..commands.use_command import UseCommand
    from ..commands.doctor_command import DoctorCommand
    from ..core import sticky as sticky_store
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
        UseCommand(), DoctorCommand(), HelpCommand(), InjectCommand(),
    ]
    ctx = CommandContext(settings=settings, registry=reg, transport=transport, telegram=tg)
    # 고정 타겟(sticky) 영속 파일 로드 — /use N 으로 설정한 chat→slot 복원.
    try:
        ctx.sticky = sticky_store.load(settings.data_dir)
    except Exception as e:
        log.warning("sticky load failed: %s", e)

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

    def _sticky_num() -> int | None:
        """현재 고정 타겟 번호(단일 채팅). None=고정 없음."""
        s = ctx.sticky.get(str(settings.allowed_chat_id))
        try:
            return int(s) if s is not None else None
        except (TypeError, ValueError):
            return None

    log.info("router start: slots=%d data_dir=%s", settings.max_slots, settings.data_dir)
    try:
        board.refresh_if_changed()   # 시작 시 공지 동기화(있으면)
    except Exception as e:
        log.warning("init board refresh failed: %s", e)

    while True:
        # heartbeat: ask_hook 이 이 파일 신선도로 router 생존을 추정해 죽어있으면
        # 최대 대기(280s)를 다 채우지 않고 조기에 네이티브 UI 로 폴백한다
        # (2026-07-04 실사고: router 좀비 상태를 훅이 알 방법이 없었음).
        try:
            settings.heartbeat_path.write_text(str(time.time()), encoding="utf-8")
        except Exception:
            pass

        # 감시: 죽은 슬롯 정리 + 공지 갱신.
        # 종료 알림은 채팅이 지저분해져 생략(상태 보드/​핀 + /list 로 확인).
        try:
            reg.sweep_dead(alive_fn)
            # 고정 타겟(sticky) 중 사망한 슬롯 자동 해제.
            alive_nums = {i.number for i in reg.active()}
            dead = [c for c, n in ctx.sticky.items() if n not in alive_nums]
            if dead:
                for c in dead:
                    ctx.sticky.pop(c, None)
                try:
                    sticky_store.save(settings.data_dir, ctx.sticky)
                except Exception as e:
                    log.warning("sticky save failed: %s", e)
            board.refresh_if_changed(pending_num=_pending_num(), sticky_num=_sticky_num())
        except Exception as e:
            log.warning("sweep/board error: %s", e)

        # 텔레그램 롱폴
        try:
            updates = tg.get_updates(timeout=5)
        except Exception as e:
            action, wait = classify_getupdates_error(e)
            if action == "stop":
                log.error("getUpdates auth failed(재시도 무의미): %s — 프로세스 종료", e)
                raise
            log.warning("getUpdates failed: %s — retry in %.1fs", e, wait)
            time.sleep(wait)
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
            # 답장(reply_to) 라우팅: 봇 메시지에 "답장" = 명시적 타겟(2+ 터미널).
            # reply_hook 가 송신 시 {message_id: 터미널번호} 매핑 저장 → 인입 update 의
            # reply_to_message.message_id 로 역추적. 매핑 미적중(만료/타겟이 안 닿는
            # 청크경계) 시 폴백으로 아래 pending/자동타겟/명령 흐름으로 진행.
            if text and not handled:
                rmsg_id = ((m.get("reply_to_message") or {}).get("message_id"))
                if rmsg_id:
                    from ..core.reply_map import lookup_num as _lookup_reply_num
                    mapped = _lookup_reply_num(settings.data_dir, rmsg_id)
                    if mapped:
                        try:
                            do_inject(ctx, mapped, text, str(chat))
                            board.refresh_if_changed(pending_num=None)
                            handled = True
                        except Exception as e:
                            log.exception("reply-to inject failed: %s", e)
            # 고정 타겟(sticky): 번호 없고 슬래시 아닌 본문 → 고정 슬롯으로 주입.
            # 우선순위: 명시번호(InjectCommand) > reply_to > sticky > pending > auto.
            # 슬롯 사망 시 자동 해제(sweep 도 매 틱 정리하지만 즉시 반영).
            if text and not handled and parse_leading_number(text) is None and not text.startswith("/"):
                stick = ctx.sticky.get(str(chat))
                if stick is not None:
                    sinfo = reg.get(stick)
                    if sinfo and transport.is_alive(sinfo.to_dict()):
                        try:
                            do_inject(ctx, stick, text, str(chat))
                            board.refresh_if_changed(pending_num=_pending_num(), sticky_num=_sticky_num())
                            handled = True
                        except Exception as e:
                            log.exception("sticky inject failed: %s", e)
                    else:
                        ctx.sticky.pop(str(chat), None)
                        try:
                            sticky_store.save(settings.data_dir, ctx.sticky)
                        except Exception:
                            pass
            # 선택모드 pending: 번호 없는 본문 → 대기 번호로 주입
            if text and not handled and parse_leading_number(text) is None:
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
                elif not text.startswith("/"):
                    # 자동 타겟: 활성 터미널 1개면 /N·버튼·pending 없이 본문 즉시 주입.
                    # 2개+ → 현행 유지(번호 명령으로 명시 선택). 슬래시명령(/list 등)은 제외.
                    actives = reg.active()
                    if len(actives) == 1:
                        try:
                            do_inject(ctx, actives[0].number, text, str(chat))
                            board.refresh_if_changed(pending_num=None)
                            handled = True
                        except Exception as e:
                            log.exception("auto-target inject failed: %s", e)
            if not handled:
                for cmd in commands:
                    try:
                        if cmd.match(msg):
                            cmd.handle(msg, ctx)
                            board.refresh_if_changed(pending_num=_pending_num())
                            break
                    except Exception as e:
                        log.exception("command %s failed: %s", type(cmd).__name__, e)
