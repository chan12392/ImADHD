"""PreToolUse 훅: CC 가 AskUserQuestion 호출 → 질문을 텔레그램 인라인 버튼으로
송신하고 답을 기다렸다가 CC 에 updatedInput.answers 를 공급한다.

네이티브 질문 UI 를 띄우지 않고 텔레그램 한 채팅에서 답을 받는 것이 목적.
(대표님 요구: "질문한다면 인라인 창으로 답변하고 그 답변의 클릭에 맞게 작업 진행")

stdin (CC hook payload):
  {session_id, tool_name:"AskUserQuestion",
   tool_input:{questions:[{question,header,options:[{label,description}],multiSelect}], ...}}

출력(JSON to stdout) — CC 가 AskUserQuestion 의 답을 훅 출력으로 받아들임:
  답 도착:
    {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow",
                           "updatedInput":{...tool_input, "answers":{<질문>:<라벨>}}}}
  시간초과:
    {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
                           "reason":"...텔레그램 응답 시간초과..."}}
  미구성(allowed_chat_id 없음/송신 실패): 빈 출력 → CC 네이티브 UI 폴백.

주의: stdout 에는 JSON 만 출력(다른 print 금지 — CC 가 stdout 을 파싱).
진단은 ~/.imadhd/debug.log.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path

# 답 대기 최대(초). CC hook timeout(300000ms=300s) 보다 여유.
DEFAULT_TIMEOUT = float(os.environ.get("IMADHD_ASK_TIMEOUT", "280"))
POLL_INTERVAL = 1.0


def _debug_log(line: str) -> None:
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)


def _last_user_text(transcript_path: str) -> str:
    """transcript JSONL 의 마지막 실사용자 텍스트(tool_result 전용 라운드 제외) 반환."""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    last = ""
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        msg = e.get("message") or e
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            last = content
            continue
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            txt = "\n".join(parts)
            if txt.strip():
                last = txt
    return last


def _origin_has_marker(transcript_path: str, marker: str) -> bool:
    """이번 turn 을 촉발한 user 메시지가 마커로 끝나는지(=텔레그램 인입 요청).
    마커 없으면 터미널 직접 작업 → 텔레그램 라우팅 skip(네이티브 UI)."""
    if not transcript_path:
        return False
    text = _last_user_text(transcript_path)
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return marker in line
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "AskUserQuestion":
        return 0
    tool_input = payload.get("tool_input") or {}
    questions = tool_input.get("questions") or []
    if not questions:
        return 0
    session_id = payload.get("session_id", "") or ""

    from ..config import Settings
    from ..core import ask_manager
    from ..core.registry import JSONFileRegistry
    from ..telegram_api.client import TelegramClient

    # 미구성(토큰/chat 없음) → CC 네이티브 UI 폴백. 사용자 막지 않음.
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[ask] settings load failed: {e!r} — native UI fallback")
        return 0

    chat_id = s.allowed_chat_id
    if not chat_id:
        # allow_any_chat 모드 등 단일 채팅 미지정 → 라우팅 불가 → 네이티브 UI.
        return 0

    transcript_path = payload.get("transcript_path")
    if not _origin_has_marker(transcript_path, s.reply_marker):
        # 이번 turn 이 텔레그램 인입([A.D.H.D])이 아니면(=터미널 직접 작업) 라우팅 skip.
        _debug_log(f"[ask] no origin marker ({s.reply_marker}) — native UI fallback")
        return 0

    reg = JSONFileRegistry(s.registry_path, s.max_slots)
    info = reg.find_by_session(session_id)
    slot = info.number if info else None
    prefix = f"{slot}️⃣ " if slot else ""

    tg = TelegramClient(s.bot_token, s.offset_path, s.allowed_chat_id)

    ask_id = ask_manager.new_ask_id()
    items = []
    for q in questions:
        opts = q.get("options") or []
        items.append({
            "question": q.get("question", ""),
            "header": q.get("header", ""),
            "options": [
                {"label": o.get("label", ""), "description": o.get("description", "")}
                for o in opts
            ],
            "message_id": None,
            "answer": None,
        })

    # 질문마다 1개 메시지(인라인 버튼 포함) 송신. 다중질문은 메시지 분리.
    sent = 0
    for i, it in enumerate(items):
        lines = [f"❓ {prefix}{it['question']}"]
        if it["header"]:
            lines.append(f"[{it['header']}]")
        for oi, opt in enumerate(it["options"]):
            d = opt.get("description")
            lines.append(f"  {oi + 1}. {opt['label']}" + (f" — {d}" if d else ""))
        markup = {"inline_keyboard": ask_manager.build_inline_keyboard(it["options"], ask_id, i)}
        try:
            mid = tg.send(chat_id, "\n".join(lines), reply_markup=markup)
            it["message_id"] = mid
            sent += 1
        except Exception as e:
            _debug_log(f"[ask] send failed q{i}: {e!r}")

    if sent == 0:
        # 송신 전부 실패 → CC 네이티브 UI 폴백.
        _debug_log(f"[ask] all sends failed ask_id={ask_id} — native UI fallback")
        return 0

    record = {
        "ask_id": ask_id,
        "session_id": session_id,
        "chat_id": str(chat_id),
        "slot": slot,
        "items": items,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
    }
    ask_manager.write_record(s.data_dir, record)
    _debug_log(
        f"[ask] sent ask_id={ask_id} slot={slot} questions={len(items)} session={session_id[:8]}"
    )

    # 답 대기(폴링) — router 가 callback 로 items[].answer 를 채운다.
    deadline = time.monotonic() + DEFAULT_TIMEOUT
    answered = False
    cur = record
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        cur = ask_manager.load_record(s.data_dir, ask_id)
        if cur and ask_manager.all_answered(cur):
            cur["status"] = "answered"
            ask_manager.write_record(s.data_dir, cur)
            answered = True
            break

    if answered:
        answers = ask_manager.record_answers(cur)
        _debug_log(f"[ask] answered ask_id={ask_id} answers={answers}")
        updated = dict(tool_input)
        updated["answers"] = answers
        _emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": updated,
            }
        })
        return 0

    # 시간초과 → deny(정직). 모델이 사유 보고 다시 질문 유도.
    cur = ask_manager.load_record(s.data_dir, ask_id) or record
    cur["status"] = "timeout"
    ask_manager.write_record(s.data_dir, cur)
    _debug_log(f"[ask] timeout ask_id={ask_id}")
    try:
        tg.send(
            chat_id,
            f"{prefix}⏰ 응답 시간초과({int(DEFAULT_TIMEOUT)}s). "
            "터미널에서 직접 응답하거나 다시 질문하세요.",
        )
    except Exception:
        pass
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "reason": (
                f"텔레그램 응답 시간초과({int(DEFAULT_TIMEOUT)}s). "
                "터미널에서 직접 응답하거나 다시 질문."
            ),
        }
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
