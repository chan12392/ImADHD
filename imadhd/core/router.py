"""라우터 메인루프: 텔레그램 롱폴 → 명령 매칭 → 주입/회신.

매 폴링 전 감시(sweep): 죽은 터미널 슬롯 정리 + "❌ N번 종료" 알림 + 공지 갱신.
확장: commands 리스트에 Command 추가하면 자동 인식.
"""
from __future__ import annotations

import logging
import time
import urllib.error
from pathlib import Path
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


def _hwnd_valid(hwnd: int) -> bool:
    """hwnd 가 살아있는 창인지. 비Windows·0·파괴 → False."""
    try:
        if not hwnd:
            return False
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        return bool(user32.IsWindow(int(hwnd)))
    except Exception:
        return False


def sync_alive(reg, log=None) -> int:
    """살아있는 claude.exe 중 registry 미등록·hwnd 무효 슬롯 자가치유.

    SessionStart 훅 의존 보완(2026-07-06). 훅이 안 돈 CC(일반 `claude`·/resume·
    pid 교체 후 훅 누락)을 라우터가 매 틱 발견 → register_alive_cc 로 지연 등록.
    이미 등록된 pid 도 hwnd 무효(0/파괴)면 재등록으로 hwnd/session 갱신(복구).
    단일 CC 우선(대표님 사용 패턴). 다중 CC 는 각각 등록 → auto 주입은 여전히
    active 길이 1일 때만(명시번호로 선택).
    반환: 이번 틱에 (신규등록 + hwnd갱신) 시도한 pid 수.
    """
    try:
        from . import proc_win
        from ..hooks.register_hook import register_alive_cc
    except Exception as e:
        if log:
            log.warning("sync_alive import failed: %s", e)
        return 0
    try:
        alive = proc_win.claude_pids()
        if not alive:
            return 0
        by_pid = {info.pid: info for info in reg.active()}
        needs: list[int] = []
        for cc_pid in alive:
            info = by_pid.get(int(cc_pid))
            if info is None:
                needs.append(int(cc_pid))
            elif not _hwnd_valid(info.hwnd):
                needs.append(int(cc_pid))  # hwnd 무효 → 갱신
        for cc_pid in needs:
            register_alive_cc(cc_pid, reg)
        return len(needs)
    except Exception as e:
        if log:
            log.warning("sync_alive error: %s", e)
        return 0


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
    from ..commands.label_command import LabelCommand
    from ..commands.help_command import HelpCommand
    from ..commands.update_adhd_command import UpdateAdhdCommand
    from ..commands.use_command import UseCommand
    from ..commands.doctor_command import DoctorCommand
    from ..core import sticky as sticky_store
    from ..core import slot_picker
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
        UseCommand(), LabelCommand(), DoctorCommand(), HelpCommand(),
        UpdateAdhdCommand(), InjectCommand(),
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
        from ..core import perm_manager
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
        # s: = slot 선택 팝업(/close /stop /use /new 인자 없음 → 인라인 번호 선택).
        if cbdata.startswith("s:"):
            parsed = slot_picker.parse_callback(cbdata)
            if not parsed:
                try: tg.answer_callback(cq, "⚠️ 알 수 없는 버튼")
                except Exception: pass
                return
            action, num = parsed
            # 가상 Message("/close 3") → 해당 Command.handle 재진입.
            # parts[1] 있으므로 정상 경로(send_picker 우회), 순환 아님.
            # num=0(use 해제 버튼) → /use 0 → use_command 해제 분기.
            from ..commands.base import Message
            _, trigger = slot_picker.ACTIONS[action]
            fake = Message(chat_id=str(chat), text=f"/{trigger} {num}", raw={})
            try:
                for cmd in commands:
                    if cmd.match(fake):
                        cmd.handle(fake, ctx); break
                done_label = "고정 해제" if (action == "use" and num == 0) else f"{action} {num}"
                tg.answer_callback(cq, f"✅ {done_label}")
                board.refresh_if_changed(pending_num=_pending_num())
            except Exception as e:
                log.exception("slot callback %s failed: %s", action, e)
                try: tg.answer_callback(cq, "⚠️ 처리 실패")
                except Exception: pass
            # 팝업 메시지 버튼 제거(빈 inline_keyboard).
            try:
                tg.edit_message_reply_markup(str(chat), cmsg.get("message_id"),
                                             {"inline_keyboard": []})
            except Exception:
                pass
            return
        # u: = update-adhd 인라인 Yes/No(대표님 2026-07-07). handle() 가 버전표시+
        # 체인지로그+yes/no 팝업 송신 → 콜백 yes → run_update() 분리(pull→pytest→restart).
        if cbdata.startswith("u:"):
            parts = cbdata.split(":")
            # 형식 u:update:yes|no. 불일치 → 토스트만.
            if (len(parts) != 3 or parts[1] != "update"
                    or parts[2] not in ("yes", "no")):
                try: tg.answer_callback(cq, "⚠️ 알 수 없는 버튼")
                except Exception: pass
                return
            choice = parts[2]
            # 팝업 버튼 즉시 제거(중복 탭 방지).
            try:
                tg.edit_message_reply_markup(str(chat), cmsg.get("message_id"),
                                             {"inline_keyboard": []})
            except Exception:
                pass
            if choice == "no":
                tg.answer_callback(cq, "🚫 취소")
                tg.send(str(chat), "🚫 업데이트 취소함")
                return
            tg.answer_callback(cq, "🔄 시작")
            from ..commands.update_adhd_command import run_update
            try:
                run_update(tg, str(chat))
            except Exception as e:
                log.exception("update-adhd callback failed: %s", e)
                tg.send(str(chat), f"⚠️ 업데이트 처리 실패: {e}")
            return
        # p: = 위험도구 승인(perm_hook PreToolUse). a: = AskUserQuestion(ask_hook).
        if cbdata.startswith("p:"):
            parsed = perm_manager.parse_callback(cbdata)
            if not parsed:
                try:
                    tg.answer_callback(cq, "⚠️ 알 수 없는 버튼")
                except Exception:
                    pass
                return
            perm_id, choice = parsed
            record = perm_manager.load_record(settings.data_dir, perm_id)
            if not record:
                try:
                    tg.answer_callback(cq, "⚠️ 만료된 승인")
                except Exception:
                    pass
                return
            # 중복 클릭 → 현재 상태만 안내, 변경 없음.
            if record.get("answer") in ("yes", "no"):
                try:
                    tg.answer_callback(cq, "이미 처리됨")
                except Exception:
                    pass
                return
            record["answer"] = choice
            record["status"] = "approved" if choice == "yes" else "denied"
            perm_manager.write_record(settings.data_dir, record)
            try:
                tg.answer_callback(cq, "✅ 승인" if choice == "yes" else "🚫 거부")
            except Exception:
                pass
            # 메시지 결과 표시로 edit + 버튼 제거(빈 inline_keyboard).
            message_id = record.get("message_id")
            if message_id:
                mark = "✅ 승인됨" if choice == "yes" else "🚫 거부됨"
                try:
                    tg.edit_message_text(
                        str(chat), message_id,
                        f"{mark}:\n{record.get('summary', '')}",
                        reply_markup={"inline_keyboard": []},
                    )
                except Exception as e:
                    log.warning("perm edit_message failed: %s", e)
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

    def _handle_photo(m: dict, chat: str, update_id) -> None:
        """TG→CC 이미지: 가장 큰 size 다운로드 → inbox 저장 → 활성 CC에 경로 주입.

        CC는 텍스트 입력만 받으므로 이미지를 inbox 디렉토리에 저장하고 **경로**를
        주입 → CC가 Read 도구로 이미지 분석(멀티모달). slot 해석 = pending →
        sticky → active 단일. 캡션은 본문에 추가."""
        photos = m.get("photo") or []
        if not photos:
            return
        biggest = max(photos, key=lambda p: p.get("file_size") or 0)
        file_id = biggest.get("file_id")
        if not file_id:
            return
        img_dir = Path(settings.data_dir) / "inbox"
        uid = update_id if update_id is not None else (file_id[:8] or "x")
        dest = img_dir / f"tg_{uid}.jpg"   # 텔레그램 photo = 항상 jpg
        try:
            path = tg.download_file(file_id, dest)
        except Exception as e:
            tg.send(chat, f"❌ 이미지 다운로드 실패: {e!r}")
            return
        # slot 해석: pending → sticky → active 단일
        num: int | None = None
        pend = ctx.pending.get(chat)
        if pend:
            num = pend[0]
        if num is None:
            stick = ctx.sticky.get(chat)
            if stick is not None:
                try:
                    num = int(stick)
                except (TypeError, ValueError):
                    num = None
        if num is None:
            actives = reg.active()
            if len(actives) == 1:
                num = actives[0].number
        if num is None:
            tg.send(chat, f"✅ 이미지 저장: {path}\n(열린 CC 없음 — 번호 지정 후 재전송)")
            return
        caption = (m.get("caption") or "").strip()
        body = f"이미지 수신: {path}"
        if caption:
            body += f"\n{caption}"
        try:
            do_inject(ctx, num, body, chat)
            tg.send(chat, f"📸 이미지 → {num}번 ({path.name})")
        except Exception as e:
            tg.send(chat, f"❌ 주입 실패: {e!r}")

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
            # 자가치유: 살아있는 CC 미등록·hwnd무효 슬롯 런타임 등록(훅 누락 보완).
            try:
                sync_alive(reg, log)
            except Exception as e:
                log.warning("sync_alive wrapper error: %s", e)
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
            log.info("upd rcvd uid=%s chat=%s allowed=%s text=%r", upd.get('update_id'), chat,
                     str(chat) == str(settings.allowed_chat_id or ""), text)
            handled = False
            # TG→CC 이미지: photo 메시지(캡션 optional). 다운로드 → inbox 저장 → 경로 주입.
            # text 빈 메시지라도 photo 있으면 여기서 처리 후 continue 흐름.
            if m.get("photo") and not handled:
                try:
                    _handle_photo(m, str(chat), upd.get("update_id"))
                except Exception as e:
                    log.exception("photo handling failed: %s", e)
                board.refresh_if_changed(pending_num=_pending_num(), sticky_num=_sticky_num())
                continue
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
            # ★ 명령(slash) 최우선: "📋 list" "📌 pin" 등 이모지+영문 버튼 텍스트도
            # normalize → match 로 잡음. sticky/pending/auto 가드가 text.startswith("/")
            # 로만 걸러서 이모지 lead 슬래시 명령이 본문 주입으로 빠져 create 가 안
            # 돌던 버그 수정 (2026-07-07).
            if text and not handled:
                for cmd in commands:
                    if cmd.match(msg):
                        try:
                            cmd.handle(msg, ctx)
                        except Exception as e:
                            log.exception("command %s failed: %s", type(cmd).__name__, e)
                        handled = True
                        break
            # 고정 타겟(sticky): 번호 없고 슬래시 아닌 본문 → 고정 슬롯으로 주입.
            # 우선순위: 명시번호(InjectCommand) > reply_to > 명령 > sticky > pending > auto.
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
