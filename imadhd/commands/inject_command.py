"""번호 명령: 이모지(N️⃣) 또는 슬래시(/N) 파싱 → 사전체크 → (선택모드 pending | 즉시주입).

세 흐름:
  A) 버튼 클릭 / `/N` 단독: 선택모드 pending 등록 (안내 생략, 채팅 최소)
     → router가 다음 본문 메시지를 해당 번호로 주입 (PENDING_TTL 초 내)
  B) N️⃣<본문> 또는 /N<본문> 직접 타이핑: 즉시 주입
  (같은 번호 재선택 → 대기 취소 토글)
"""
from __future__ import annotations

import datetime
import hashlib
import re
import time
from pathlib import Path

from .base import Command, Message, CommandContext, resolve_active_slot

# register(SessionStart) 직후 CC REPL 이 아직 입력을 못 받는 초기화 구간이
# 있다(2026-07-05 실사고: 새 세션 열자마자 즉시 주입하면 텍스트+Enter 가
# 씹히고 실제 user/assistant 턴 없이 Stop 훅만 헛되게 발동 → transcript
# 파일 자체가 안 생기고 세션이 dead-end 됨). 세션 시작 후 이 유예시간
# 안에는 주입 전 남은 시간만큼 대기.
READY_GRACE_SEC = 2.5


def _debug_log(line: str) -> None:
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _input_fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return f"len={len(text)} sha256={digest}"


def mark_marker_pending(data_dir, session_id: str) -> None:
    """주입 = 항상 회신 대상 턴. reply_hook 이 Stop 시점에 transcript 로만
    "이 턴이 텔레그램 인입이었는지" 재판정하면 cold-start flush 지연
    (2026-07-05 실사고: session=0d38e2b2, exists=False 오판 → 회신 유실)에
    놓친다. 주입 시점에 파일로 미리 남겨 transcript 상태와 무관하게 판정.
    이름은 레거시(mark_marker_pending)지만 이제 마커 문자열과 무관 —
    '회신 대상 턴' 플래그."""
    if not session_id or not data_dir:
        return
    try:
        d = Path(data_dir) / "marker_pending"
        d.mkdir(parents=True, exist_ok=True)
        (d / session_id).write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


# 숫자이모지 → 숫자 매핑 (1..6, 여유분 7..9 포함)
EMOJI_TO_NUM = {
    "1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5, "6️⃣": 6,
    "7️⃣": 7, "8️⃣": 8, "9️⃣": 9,
}

# 슬래시 명령: /1 .. /9. (?!\d) 로 /10 등 두자리 방지(그건 일반 메시지).
# \s* 로 /1<공백>본문, /1본문(공백없음) 둘 다 허용.
SLASH_RE = re.compile(r"^/([1-9])(?!\d)\s*(.*)$", re.DOTALL)

PENDING_TTL = 600  # 선택 대기 10분 초과 → 자동 해제(초). 취소(같은 번호 재클릭) 가능하므로 여유.


class InjectCommand(Command):
    def match(self, msg: Message) -> bool:
        return bool(msg.text) and (_starts_with_num_emoji(msg.text) or bool(SLASH_RE.match(msg.text)))

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        num = parse_leading_number(msg.text)
        if num is None:
            return
        _, info = resolve_active_slot(
            msg,
            ctx,
            num,
            missing_message=f"❌ {num}번 터미널 없음",
            dead_message=f"❌ {num}번 터미널 종료",
        )
        if not info:
            return
        body = msg.text[len(leading_prefix(msg.text)):].strip()
        # A) 단독 선택(번호만/상태마크/점) → 선택모드 pending 토글
        clean = body.replace(".", "").strip()
        if not clean or clean in {"⭕", "❌", "📝"}:
            chat = str(msg.chat_id)
            existing = ctx.pending.get(chat)
            if existing and existing[0] == num:
                del ctx.pending[chat]                       # 같은 번호 재선택 → 대기 취소
                _debug_log(f"[select] num={num} pending cancelled")
            else:
                ctx.pending[chat] = (num, time.time())      # 신규/다른 번호 → 대기 교체
                _debug_log(f"[select] num={num} pending set")
            return
        # B) 본문 있으면 즉시 주입
        do_inject(ctx, num, body, msg.chat_id)


def _normalize_question(body: str) -> str:
    """선두 '?' 를 '뭐? ' 로 변환.

    CC 가 터미널 선두 '?' 입력을 기본 도움말 단축키로 해석 → 주입이 무시됨(버그 아님).
    텔레그램 '?' 로 시작하는 질문은 "뭐? <본문>" 으로 바꿔 CC 가 질문으로 인식.
    '?' 여러 개도 한 번에 처리. 본문 없으면 "뭐?".
    """
    if body.startswith("?"):
        rest = body.lstrip("?").strip()
        return f"뭐? {rest}".strip()
    return body


def do_inject(ctx: CommandContext, num: int, body: str, chat_id: str) -> None:
    """주입 공통 로직: alive 재체크 + 본문 정규화 + 주입 + busy 표시.

    InjectCommand(즉시 주입) 와 router(pending 본문 주입) 모두 사용.
    """
    _, info = resolve_active_slot(
        Message(str(chat_id), "", {}),
        ctx,
        num,
        missing_message=f"❌ {num}번 터미널 없음",
        dead_message=f"❌ {num}번 터미널 종료",
    )
    if not info:
        return
    try:
        started = datetime.datetime.fromisoformat(info.started_at)
        elapsed = (datetime.datetime.now() - started).total_seconds()
        if 0 <= elapsed < READY_GRACE_SEC:
            wait = READY_GRACE_SEC - elapsed
            _debug_log(f"[inject] num={num} ready-grace wait={wait:.2f}s (elapsed={elapsed:.2f}s)")
            time.sleep(wait)
    except Exception:
        pass
    _debug_log(f"[inject] num={num} hwnd={info.hwnd} pid={info.pid} session={info.session_id[:8]}")
    # 한 줄 주입: \n은 CC 터미널에서 Enter(제출)로 작동해 분할되므로 제거
    body = _normalize_question(" ".join(body.split()) or "(빈 입력)")
    # CC 프롬프트에 마커/표식 안 붙임 — CC는 텔레그램 인입 사실을 모름.
    # 회신 결정·길이 교정은 전부 reply_hook(Stop)이 pending 플래그로 처리.
    inject_text = body
    ctx.registry.set_status(num, "busy")   # 📝 작업중 표시
    mark_marker_pending(ctx.settings.data_dir, info.session_id)
    result = ctx.transport.inject(info.to_dict(), inject_text)
    _debug_log(
        f"[inject-done] num={num} method={getattr(result, 'method', '?')} "
        f"delivered={getattr(result, 'delivered', False)} {_input_fingerprint(inject_text)}"
    )
    # transport 가 InjectResult(진짜) 반환 시에만 복구 처리. 테스트 FakeTransport(None) 방어.
    new_hwnd = getattr(result, "rediscovered_hwnd", None)
    if new_hwnd:
        # stale hwnd 복구 → registry 에 현재 hwnd 영속(다음 주입은 즉시 성공).
        # status(busy) 보존: set_hwnd 는 status 안 건드림.
        ctx.registry.set_hwnd(num, new_hwnd)
        _debug_log(f"[inject] num={num} hwnd 복구 {info.hwnd} → {new_hwnd}")


def _starts_with_num_emoji(text: str) -> bool:
    return any(text.startswith(e) for e in EMOJI_TO_NUM)


def parse_leading_number(text):
    """선두 숫자이모지 또는 /N → int. 없으면 None."""
    if not text:
        return None
    for emoji, n in EMOJI_TO_NUM.items():
        if text.startswith(emoji):
            return n
    m = SLASH_RE.match(text)
    if m:
        return int(m.group(1))
    return None


def leading_prefix(text):
    """선두 접두(숫자이모지 또는 /N) 반환. 없으면 ''. body = text[len(prefix):]."""
    if not text:
        return ""
    for emoji in EMOJI_TO_NUM:
        if text.startswith(emoji):
            return emoji
    m = SLASH_RE.match(text)
    if m:
        return f"/{m.group(1)}"
    return ""
