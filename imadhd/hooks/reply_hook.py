"""Stop 훅: CC 응답 종료 → transcript 마지막 assistant 답변 읽기 →
마커 감지 → 회신 (session_id→번호 역조회, 숫자이모지 붙여 전송).

인입(inject_command 가 주입한) 메시지엔 마커가 있는데 CC 응답 마지막 줄에
마커가 없으면(CLAUDE.md 규칙을 깜빡함) 조용히 통과하지 않고 Stop 을
block 해서 마커를 다시 출력하게 한다 — 작업은 끝났는데 회신만 안 가는
silent failure 방지(2026-07-04 실사고: 마커 누락으로 텔레그램 회신
자체가 안 감. channel-reply-guard.py 와 동일 패턴을 이 훅에 흡수해
별도 Stop 훅 프로세스를 추가하지 않음).

stdin: CC hook payload JSON (session_id, transcript_path, stop_hook_active).
stop_hook_active=True 면 통과(무한루프 방지).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path


def _mask_token(s) -> str:
    """예외 repr/로그에서 bot token URL 노출 방지(2026-07-07 보안 P1#6).
    텔레그램 Bot API 는 token 이 URL path 에 들어가 HTTPError repr 등에
    그대로 노출 — debug.log 를 실수로 공유하면 token 유출."""
    return re.sub(r"bot\d+:[A-Za-z0-9_-]{20,}", "bot<redacted>", str(s))

# Stop 훅 실행 시점에 transcript jsonl 이 아직 디스크에 flush 안 된 레이스가
# 있다(2026-07-05 실사고: exists=False, text_len=0 으로 빠져 should_reply=False
# → 마커 있어도 텔레그램 회신 자체가 스킵됨). 파일 나타날 때까지 짧게 재시도.
TRANSCRIPT_RETRY_SEC = 8.0
TRANSCRIPT_RETRY_INTERVAL_SEC = 0.2

# marker_pending 플래그 유효기간(초). 이보다 오래된 파일은 죽은 세션의
# 잔재로 간주하고 무시+삭제(무한 누적 방지).
MARKER_PENDING_TTL_SEC = 3600.0

# 텔레그램 회신 길이 게이트(대표님 mem0 선호: 700자 이하 권장, 1200자 최대).
# HARD 초과 + 회신대상턴 + 재시도 아님 → 1회 block("짧게 다시").
# stop_hook_active(재시도)면 포기하고 전체 전송(길어도 청크분할로 감당).
REPLY_SOFT_LIMIT = 700
REPLY_HARD_LIMIT = 1200


def _get_role(entry: dict) -> str | None:
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("role")
    return entry.get("role") if isinstance(entry, dict) else None


def _get_content(entry: dict):
    msg = entry.get("message") if isinstance(entry, dict) else None
    if isinstance(msg, dict):
        return msg.get("content")
    return entry.get("content") if isinstance(entry, dict) else None


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def _extract_images(content) -> list:
    """CC assistant content 의 image 블록 → [{data, media_type, ext}].

    Anthropic SDK image 블록 구조(실측 2026-07-06):
      {"type":"image","source":{"type":"base64","media_type":"image/png",
                                 "data":"<base64>"}}
    base64 만 처리(URL source 는 미구현 스킵 — CC 생성 이미지는 base64).
    디코딩 실패/빈 데이터 → 스킵.
    """
    import base64 as _b64
    out: list[dict] = []
    if not isinstance(content, list):
        return out
    for b in content:
        if not isinstance(b, dict) or b.get("type") != "image":
            continue
        src = b.get("source") or {}
        if src.get("type") != "base64":
            continue
        try:
            raw = _b64.b64decode(src.get("data", "") or "")
        except Exception:
            continue
        if not raw:
            continue
        mt = src.get("media_type", "image/png") or "image/png"
        ext = "jpg" if ("jpeg" in mt or "jpg" in mt) else "png"
        out.append({"data": raw, "media_type": mt, "ext": ext})
    return out


def _last_assistant_images(entries: list) -> list:
    """마지막 assistant entry 의 image 블록들 추출(CC→TG 이미지 회신).

    _last_assistant_text 와 동일 entry 에서 뽑는다(text+image 가 같은
    assistant 메시지에 공존 가능). assistant entry 가 여러 개면 가장 마지막 것."""
    for entry in reversed(entries):
        if _get_role(entry) != "assistant":
            continue
        imgs = _extract_images(_get_content(entry))
        if imgs:
            return imgs
    return []


def _is_external_user_message(entry: dict) -> bool:
    """tool_result 만 있는 user round(API 왕복)는 실제 사용자 발화가 아니므로 제외."""
    if _get_role(entry) != "user":
        return False
    content = _get_content(entry)
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") in ("text", "image")
            for b in content
        )
    return False


def last_user_text_from_entries(entries: list) -> str:
    for entry in reversed(entries):
        if _is_external_user_message(entry):
            return _extract_text(_get_content(entry))
    return ""


def _read_entries(transcript_path: str) -> list:
    p = Path(transcript_path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line
    return ""


def reply_too_long(text: str, limit: int = REPLY_HARD_LIMIT) -> bool:
    """회신 본문이 limit 자 초과면 True(=짧게 다시 block 대상)."""
    return len(text or "") > limit


def _marker_pending_path(data_dir, session_id: str) -> Path:
    return Path(data_dir) / "marker_pending" / session_id


def has_marker_pending(data_dir, session_id: str) -> bool:
    """inject_command.mark_marker_pending 이 남긴 플래그 확인.

    transcript 를 못 읽어도(cold-start flush 지연) "이 세션은 텔레그램
    inject 로 시작된 마커 턴"이라는 사실 자체는 이 파일로 독립적으로
    안다 — 2026-07-05 실사고(session=0d38e2b2) 재발 방지."""
    if not session_id:
        return False
    p = _marker_pending_path(data_dir, session_id)
    try:
        if not p.exists():
            return False
        age = time.time() - float(p.read_text(encoding="utf-8").strip() or "0")
        if age > MARKER_PENDING_TTL_SEC:
            p.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        return False


def clear_marker_pending(data_dir, session_id: str) -> None:
    if not session_id:
        return
    try:
        _marker_pending_path(data_dir, session_id).unlink(missing_ok=True)
    except Exception:
        pass


def _debug_log(line: str) -> None:
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _resolve_transcript_path(transcript_path: str, session_id: str) -> Path:
    """전달받은 transcript_path 가 아직 없으면 session_id 로 실제 파일을 재탐색.

    CC가 SessionStart/Stop 훅에 넘기는 transcript_path 는 파일이 flush 되기
    전 시점 값일 수 있다. 같은 session_id.jsonl 이 다른 하위경로에 이미
    존재하는 경우도 있어 폭넓게(glob) 재탐색한다.
    """
    requested = Path(transcript_path)
    if requested.is_file():
        return requested
    if not session_id:
        return requested
    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return requested
    try:
        for p in root.glob(f"*/{session_id}.jsonl"):
            if p.is_file():
                return p
        for p in root.glob(f"*/{session_id}/**/*.jsonl"):
            if p.is_file():
                return p
    except Exception as e:
        _debug_log(f"[reply] transcript resolve failed session={session_id[:8]} err={e!r}")
    return requested


def _last_assistant_text_retry(transcript_path: str, session_id: str, reader) -> tuple[str, str, bool]:
    deadline = time.monotonic() + TRANSCRIPT_RETRY_SEC
    last_path = Path(transcript_path)
    while True:
        last_path = _resolve_transcript_path(transcript_path, session_id)
        try:
            text = reader(str(last_path))
        except Exception as e:
            _debug_log(f"[reply] transcript read failed session={session_id[:8]} path={last_path} err={e!r}")
            text = ""
        if text:
            return text, str(last_path), last_path.exists()
        if time.monotonic() >= deadline:
            return "", str(last_path), last_path.exists()
        time.sleep(TRANSCRIPT_RETRY_INTERVAL_SEC)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _debug_log("[reply] stdin parse failed")
        return 0
    stop_hook_active = bool(payload.get("stop_hook_active"))

    session_id = payload.get("session_id", "") or ""
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        _debug_log(f"[reply] no transcript_path session={session_id[:8]}")
        return 0
    exists = Path(transcript_path).exists()
    _debug_log(
        f"[reply] session={session_id[:8]} transcript={transcript_path} "
        f"exists={exists} stop_hook_active={stop_hook_active}"
    )

    from .register_hook import _last_assistant_text
    from ..config import Settings
    from ..core.registry import JSONFileRegistry
    from ..reply.marker_capture import MarkerCapture, ReplyPayload
    from ..reply.markup import md_to_tg_html
    from ..commands.inject_command import EMOJI_TO_NUM
    from ..telegram_api.client import TelegramClient

    # 설정 미구성/일시 오독(.env 등) → 회신·상태갱신만 스킵. Stop 자체는 막지 않음
    # (예외 미처리 시 훅이 죽어 idle 복귀도 회신도 안 되고 busy 로 영구 고정됨).
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[reply] Settings.load failed: {e!r}")
        return 0
    text, resolved_transcript_path, resolved_exists = _last_assistant_text_retry(
        transcript_path, session_id, _last_assistant_text
    )
    if resolved_transcript_path != transcript_path or resolved_exists != exists:
        _debug_log(
            f"[reply] resolved transcript session={session_id[:8]} "
            f"from={transcript_path} to={resolved_transcript_path} exists={resolved_exists}"
        )
    transcript_path = resolved_transcript_path
    mc = MarkerCapture(s.reply_marker)
    rp = ReplyPayload(session_id, transcript_path, text)

    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    info = reg.find_by_session(session_id)
    emoji = ""
    if info:
        inv = {v: k for k, v in EMOJI_TO_NUM.items()}
        emoji = inv.get(info.number, f"[{info.number}]")
        reg.set_status_by_session(session_id, "idle")   # 작업 완료 → ⭕ 복귀 (마커 무관 — 터미널 직접 작업도 busy_hook 진입했으면 복귀)
    else:
        _debug_log(f"[reply] no registry match session={session_id[:8]}")

    # 회신 대상 턴 = 텔레그램 inject 로 시작(inject가 pending 세팅). 레거시
    # user_text 마커(구버전 inject가 붙이던 [A.D.H.D])도 보조 신호로 인정.
    # 마커 echo 여부는 회신 조건에서 완전 제거 — CC가 터미널 직접 타이핑에
    # 마커를 과잉 출력해도(2026-07-06 session=c4f60955 실측) 텔레그램로 새어
    # 나가지 않는다. CC는 텔레그램 인입 사실을 모른다(프롬프트에 표식 無).
    entries = _read_entries(transcript_path)
    user_text = last_user_text_from_entries(entries)
    pending_flag = has_marker_pending(s.data_dir, session_id)
    is_marker_turn = (s.reply_marker in user_text) or pending_flag
    too_long = reply_too_long(text)
    images = _last_assistant_images(entries)
    _debug_log(
        f"[reply] session={session_id[:8]} text_len={len(text)} "
        f"too_long={too_long} is_marker_turn={is_marker_turn} "
        f"pending={pending_flag} stop_hook_active={stop_hook_active} "
        f"images={len(images)}"
    )
    # 직접 타이핑 턴 — 회신도 block 도 안 함(idle 복귀는 위에서 마커 무관 처리).
    if not is_marker_turn:
        _debug_log(f"[reply] direct-typing turn, suppress reply+block session={session_id[:8]}")
        return 0
    if not text and not images:
        _debug_log(f"[reply] marker turn but no assistant text/image session={session_id[:8]}")
        clear_marker_pending(s.data_dir, session_id)
        return 0
    # 길이 게이트 폐지(2026-07-07 대표님 결정): HARD 초과 block → CC 재작성 루프가
    # 회신 지연/누락 인상 유발(터미널↔텔레그램 전환 시 특히). 대신 client.send 가
    # 청크 분할(마크다운/줄바꿈 경계)로 전체 전송 — 누락 방지가 "짧게 강제"보다 우선.
    # 대표님 mem0 가독성 선호(700/1200)는 CC 프롬프트·청크 크기로 보존(회신 게이트 아님).
    if too_long:
        _debug_log(
            f"[reply] long reply, skip block → chunked send session={session_id[:8]} "
            f"len={len(text)}"
        )
    clear_marker_pending(s.data_dir, session_id)
    body = mc.build_text(rp)

    if not s.allowed_chat_id:
        _debug_log("[reply] no allowed_chat_id, skip send")
        return 0
    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)
    msg = f"{emoji} {body}".strip()
    # 마크다운 → Telegram HTML 렌더(코드블록/굵게/이탤릭). Markdown V1 은 코드펜스
    # 미지원 → 400 → plain 폴백 되는 문제 해결. HTML 모드 + md_to_tg_html 변환.
    # 변환/전송 실패 시 plain 폴백.
    sent_ids: list[int] = []
    if msg.strip():
        try:
            sent_ids = tg.send(s.allowed_chat_id, md_to_tg_html(msg), parse_mode="HTML")
            _debug_log(f"[reply] sent HTML ok session={session_id[:8]} chunks={len(sent_ids)}")
        except Exception as e1:
            # plain 폴백도 실패하면(4096자 초과 외 사유) 여기서 죽지 않고 조용히 포기.
            # 이 예외를 못 잡으면 Stop 훅 자체가 죽어 idle 복귀는 됐어도 회신이
            # 통째로 유실된다(2026-07-04 발견).
            try:
                sent_ids = tg.send(s.allowed_chat_id, msg)
                _debug_log(f"[reply] sent plain fallback ok session={session_id[:8]} chunks={len(sent_ids)} (html err={_mask_token(e1)})")
            except Exception as e2:
                sent_ids = []
                _debug_log(f"[reply] send FAILED both html/plain session={session_id[:8]} html_err={_mask_token(e1)} plain_err={_mask_token(e2)}")

    # CC→TG 이미지 회신: 마지막 assistant 메시지의 image 블록(base64)을
    # 디코딩해 sendPhoto 로 각각 전송. caption=번호(라우팅 식별용). text 회신과
    # 별도 메시지. 실패해도 text 회신은 이미 갔으므로 조용히 로깅만.
    image_ids: list[int] = []
    for img in images:
        try:
            mid = tg.send_photo(
                s.allowed_chat_id, img["data"], f"image.{img['ext']}",
                caption=(emoji or None),
            )
            if mid:
                image_ids.append(mid)
            _debug_log(
                f"[reply] send_photo ok session={session_id[:8]} ext={img['ext']} "
                f"bytes={len(img['data'])}"
            )
        except Exception as e:
            _debug_log(f"[reply] send_photo failed session={session_id[:8]} err={_mask_token(e)}")
    # 답장 라우팅 매핑: 봇 송신 message_id → 이 세션 터미널번호.
    # 대표님이 이 메시지에 "답장"하면 router 가 reply_to_message.message_id 로
    # 이 번호를 찾아 해당 터미널로 주입(2+ 터미널 명시적 라우팅).
    # text 청크 + image 메시지 모두 같은 slot 매핑 → 어느 쪽에 답장해도 라우팅 적중.
    if (sent_ids or image_ids) and info:
        try:
            from ..core.reply_map import store as store_reply_map
            for mid in sent_ids + image_ids:
                store_reply_map(s.data_dir, mid, info.number)
        except Exception as e:
            _debug_log(f"[reply] reply_map store failed session={session_id[:8]} err={e!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
