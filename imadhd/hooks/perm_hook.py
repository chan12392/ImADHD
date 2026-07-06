"""PreToolUse 훅: CC 가 위험 도구(rm/git push/kill/...) 호출 시 텔레그램 Yes/No
버튼으로 승인받고 결과를 CC 의 permissionDecision 으로 반환한다.

대표님 critical-ops 사전승인 정책(CLAUDE.md: rm/drop/kill/disable/restart) 부합.
네이티브 승인 UI 없이 텔레그램 한 채팅에서 결정.

동작 흐름:
  1. stdin(CC hook payload) 파싱 — {tool_name, tool_input, session_id, transcript_path}
  2. 터미널 직접 작업(마커 없음) → skip(CC 네이티브/bypass 처리)
  3. 위험 분류:
       - Bash: command 위험 토큰 regex 매칭
       - Write/Edit: (1차 구현 미게이트 — 차기 보호디렉토리 확장점)
       - 매칭 안 됨 → exit 0, 출력 없음 → CC bypass 모드로 그냥 진행(텔레그램 미송신)
  4. 매칭 → 텔레그램 Yes/No 인라인 버튼 송신 + perm 기록 쓰기
  5. 폴링(router heartbeat 40s stale 시 조기 timeout)
  6. 답 도착 → allow/deny emit / timeout → deny(정직)

출력(JSON to stdout):
  승인: {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}
  거부/시간초과: {"hookSpecificOutput":{"hookEventName":"PreToolUse",
                "permissionDecision":"deny","reason":"..."}}

bypassPermissions 모드에서도 PreToolUse deny 는 비인터랙티브 도구를 실제 차단한다
(공식문서: code.claude.com/docs/en/hooks.md#pretooluse-decision-control —
"Deny and ask rules are still evaluated regardless of what the hook returns").
동일 matcher(Bash|Write|Edit) 의 recall_hook 은 additionalContext 만 주입하고
permissionDecision 을 emit 하지 않으므로 이 훅의 결정이 충돌 없이 그대로 적용된다.

stdout 에는 JSON 만(CC 가 stdout 파싱). 진단은 ~/.imadhd/debug.log.
"""
from __future__ import annotations

import datetime
import html
import json
import re
import sys
import time

# 답 대기 최대(초). CC hook timeout(300000ms=300s) 보다 여유.
DEFAULT_TIMEOUT = float(__import__("os").environ.get("IMADHD_PERM_TIMEOUT", "280"))
POLL_INTERVAL = 1.0

# ask_hook 과 공유하는 순수 헬퍼(동일 패키지 내 재사용 — 중복 방지).
from .ask_hook import (  # noqa: E402
    router_alive, _origin_has_marker, _debug_log, _emit,
    HEARTBEAT_MAX_AGE, HEARTBEAT_CHECK_INTERVAL,
)

# 위험 명령 패턴(critical-ops 기반, 오탐 최소화).
# Bash command 내에서만 매칭(산문 아님). 대표님이 텔레그램에서 확인해야 할 행동.
# 추가/수정 시 tests/test_perm_hook.py 동기화.
DANGEROUS_PATTERNS: list[re.Pattern] = [
    # 파일/디렉토리 삭제
    re.compile(r"\brm\b", re.I),
    re.compile(r"\brmdir\b", re.I),
    re.compile(r"\brd\s+/s", re.I),
    re.compile(r"\bdel\b", re.I),
    re.compile(r"Remove-Item", re.I),
    # 강제/하드 플래그
    re.compile(r"-rf\b"),
    re.compile(r"--hard\b"),
    re.compile(r"--force\b"),
    # git 파괴적 명령
    re.compile(r"\bgit\s+push\b", re.I),
    re.compile(r"\bgit\s+reset\b", re.I),
    re.compile(r"\bgit\s+clean\b", re.I),
    re.compile(r"\bgit\s+commit\s+--amend\b", re.I),
    # 프로세스 종료
    re.compile(r"\bkill\b", re.I),
    re.compile(r"taskkill", re.I),
    re.compile(r"Stop-Process", re.I),
    # pm2 서비스 제어(봇 자신을 죽일 수 있음)
    re.compile(r"\bpm2\s+(delete|restart|stop|kill)\b", re.I),
    # 시스템 전원
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\breboot\b", re.I),
    # 권한 상승
    re.compile(r"\bsudo\b", re.I),
    # DB 파괴
    re.compile(r"\bdrop\s+(table|database|db)\b", re.I),
    re.compile(r"\btruncate\b", re.I),
    # 서비스 비활성/재기동
    re.compile(r"\bsystemctl\s+(disable|restart|stop)\b", re.I),
    re.compile(r"\bservice\s+\S+\s+(restart|stop)\b", re.I),
]


def classify_risk(tool_name: str, tool_input: dict) -> str | None:
    """위험 매칭 → 요약 문자열 반환, 안전 → None.

    Bash: command 위험 토큰 매칭. Write/Edit: 1차 미게이트(None).
    요약 = command 앞뒤 800자(텔레그램 표시용)."""
    if tool_name != "Bash":
        # Write/Edit 보호디렉토리 게이트 = 차기 확장(미구현 → 안전하게 통과).
        return None
    command = (tool_input.get("command") or "").strip()
    if not command:
        return None
    for pat in DANGEROUS_PATTERNS:
        if pat.search(command):
            # 텔레그램 표시용 요약(과도한 길이 절단).
            return command[:800]
    return None


def build_approval_body(prefix: str, tool_name: str, summary: str) -> str:
    escaped_summary = html.escape(summary, quote=False)
    return f"⚠️ {prefix}위험 명령 승인 ({tool_name}):\n<code>{escaped_summary}</code>"


def emit_deny(reason: str) -> None:
    _emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "reason": reason,
    }})


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or ""
    if tool_name not in ("Bash", "Write", "Edit"):
        return 0   # 다른 도구 = 훅 미관여

    tool_input = payload.get("tool_input") or {}
    summary = classify_risk(tool_name, tool_input)
    if summary is None:
        return 0   # 안전 → 출력 없음 → CC bypass 모드로 그냥 진행

    session_id = payload.get("session_id", "") or ""

    from ..config import Settings
    from ..core import perm_manager
    from ..core.registry import JSONFileRegistry
    from ..telegram_api.client import TelegramClient

    # 미구성(토큰/chat 없음) → fail-open(진행). 사용자 막지 않음.
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[perm] settings load failed: {e!r} — fail-open")
        return 0

    chat_id = s.allowed_chat_id
    if not chat_id:
        return 0   # 단일 채팅 미지정 → 라우팅 불가 → 진행

    transcript_path = payload.get("transcript_path")
    if not _origin_has_marker(transcript_path, s.reply_marker):
        # 터미널 직접 작업(마커 없음) → 텔레그램 skip. CC bypass 로 진행.
        _debug_log(f"[perm] no origin marker ({s.reply_marker}) — fail-open")
        return 0

    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    info = reg.find_by_session(session_id)
    slot = info.number if info else None
    prefix = f"{slot}️⃣ " if slot else ""

    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)
    perm_id = perm_manager.new_perm_id()

    body = build_approval_body(prefix, tool_name, summary)
    markup = {"inline_keyboard": perm_manager.build_inline_keyboard(perm_id)}
    try:
        mids = tg.send(chat_id, body, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        reason = "텔레그램 승인 메시지 전송 실패. 안전을 위해 거부 처리."
        _debug_log(f"[perm] send failed perm_id={perm_id}: {e!r} — deny")
        emit_deny(reason)
        return 0
    message_id = mids[-1] if mids else None

    record = {
        "perm_id": perm_id,
        "session_id": session_id,
        "chat_id": str(chat_id),
        "slot": slot,
        "tool_name": tool_name,
        "summary": summary,
        "message_id": message_id,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
        "answer": None,
    }
    perm_manager.write_record(s.data_dir, record)
    _debug_log(
        f"[perm] sent perm_id={perm_id} slot={slot} tool={tool_name} session={session_id[:8]}"
    )

    # 답 대기(폴링) — router 가 callback 으로 answer 를 채운다.
    deadline = time.monotonic() + DEFAULT_TIMEOUT
    answer: str | None = None
    router_dead = False
    last_hb_check = 0.0
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        cur = perm_manager.load_record(s.data_dir, perm_id)
        if cur and cur.get("answer") in ("yes", "no"):
            answer = cur["answer"]
            cur["status"] = "approved" if answer == "yes" else "denied"
            perm_manager.write_record(s.data_dir, cur)
            break
        now = time.monotonic()
        if now - last_hb_check >= HEARTBEAT_CHECK_INTERVAL:
            last_hb_check = now
            if not router_alive(s.data_dir):
                _debug_log(f"[perm] router heartbeat stale perm_id={perm_id} — 조기 timeout")
                router_dead = True
                break

    if answer == "yes":
        _debug_log(f"[perm] approved perm_id={perm_id}")
        _emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }})
        return 0
    # 메시지 edit/토스트는 router 가 callback 수신 시 처리(ask 패턴과 동일 —
    # hook 과 router 양쪽 edit 경쟁 방지). hook 은 deny emit 만.

    # 거부(no) 또는 timeout → deny(정직).
    cur = perm_manager.load_record(s.data_dir, perm_id) or record
    if answer == "no":
        cur["status"] = "denied"
        deny_reason = "텔레그램에서 거부(No)됨."
    else:
        cur["status"] = "timeout"
        if router_dead:
            deny_reason = "router 응답 없음(재시작 필요할 수 있음). 거부 처리."
        else:
            deny_reason = f"텔레그램 승인 시간초과({int(DEFAULT_TIMEOUT)}s). 거부 처리."
    perm_manager.write_record(s.data_dir, cur)
    _debug_log(f"[perm] denied perm_id={perm_id} reason={deny_reason}")
    emit_deny(deny_reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
