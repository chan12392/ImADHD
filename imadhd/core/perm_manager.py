"""위험 도구 승인 라우팅 저장소 (PreToolUse perm_hook ↔ router 간 통신).

흐름:
  1. PreToolUse 훅(perm_hook)이 CC 의 위험 도구(rm/push/kill/...) 호출을
     텔레그램 Yes/No 인라인 버튼으로 송신하고 perm 기록을 이곳에 쓴 뒤,
     답이 도착할 때까지 폴링.
  2. router 가 버튼 클릭(callback_query)을 받아 기록에 답을 기록.
  3. 훅이 답을 꺼내 CC 의 permissionDecision(allow|deny) 으로 반환.

ask_manager 와 구조 동일. 차이:
  - callback_data prefix = "p:" (ask 는 "a:") — 라우터 분기용.
  - 항목 단일(위험 명령 요약 1개), 옵션 고정 Yes/No.

perm 기록 = data_dir/perms/<perm_id>.json:
  {
    "perm_id": "<12hex>",
    "session_id": "...", "chat_id": "...", "slot": 3 | null,
    "tool_name": "Bash", "summary": "rm -rf build/", "message_id": 123,
    "created_at": "<iso>",
    "status": "pending"|"approved"|"denied"|"timeout",
    "answer": null | "yes" | "no"
  }

원자적 쓰기(임시파일 + os.replace). 훅=읽기/폴링, router=쓰기. 단일 머신.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path


def perms_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "perms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def perm_path(data_dir: Path, perm_id: str) -> Path:
    return perms_dir(data_dir) / f"{perm_id}.json"


def new_perm_id() -> str:
    return uuid.uuid4().hex[:12]


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_record(data_dir: Path, record: dict) -> None:
    _write_atomic(perm_path(data_dir, record["perm_id"]), record)


def load_record(data_dir: Path, perm_id: str) -> dict | None:
    return _read(perm_path(data_dir, perm_id))


def build_inline_keyboard(perm_id: str) -> list[list[dict]]:
    """Yes/No 2버튼을 한 행에 배치. callback_data = "p:<perm_id>:<y|n>"."""
    return [
        [
            {"text": "✅ 승인", "callback_data": f"p:{perm_id}:yes"},
            {"text": "❌ 거부", "callback_data": f"p:{perm_id}:no"},
        ]
    ]


def parse_callback(callback_data: str) -> tuple[str, str] | None:
    """callback_data = "p:<perm_id>:<yes|no>" → (perm_id, choice).
    불일치/잘못된 choice → None."""
    if not callback_data or not callback_data.startswith("p:"):
        return None
    parts = callback_data.split(":")
    if len(parts) != 3:
        return None
    if parts[2] not in ("yes", "no"):
        return None
    return parts[1], parts[2]
