"""AskUserQuestion 답변 라우팅 저장소 (PreToolUse 훅 ↔ router 간 통신).

흐름:
  1. PreToolUse 훅(ask_hook)이 CC 의 AskUserQuestion 질문을 텔레그램 인라인
     버튼으로 송신하고 ask 기록을 이곳에 쓴 뒤, 답이 도착할 때까지 폴링.
  2. router가 버튼 클릭(callback_query)을 받아 기록에 답을 기록.
  3. 훅이 답을 꺼내 CC 의 updatedInput.answers 로 반환 → 네이티브 UI 없이 진행.

ask 기록 = data_dir/asks/<ask_id>.json:
  {
    "ask_id": "<12hex>",
    "session_id": "...", "chat_id": "...", "slot": 3 | null,
    "items": [
      {"question":"...","header":"...",
       "options":[{"label","description"}...],
       "message_id": 123, "answer": null | "<label>"}
    ],
    "created_at": "<iso>", "status": "pending"|"answered"|"timeout"
  }

원자적 쓰기(임시파일 + os.replace). 훅=읽기/폴링, router=쓰기. 단일 머신.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path


def asks_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "asks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ask_path(data_dir: Path, ask_id: str) -> Path:
    return asks_dir(data_dir) / f"{ask_id}.json"


def new_ask_id() -> str:
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
    _write_atomic(ask_path(data_dir, record["ask_id"]), record)


def load_record(data_dir: Path, ask_id: str) -> dict | None:
    return _read(ask_path(data_dir, ask_id))


def record_answers(record: dict) -> dict:
    """{질문텍스트: 선택라벨}. 답 없는 항목은 스킵. CC updatedInput.answers 용."""
    out: dict[str, str] = {}
    for it in record.get("items", []):
        ans = it.get("answer")
        if ans is not None:
            out[it["question"]] = ans
    return out


def all_answered(record: dict) -> bool:
    items = record.get("items", [])
    return bool(items) and all(it.get("answer") is not None for it in items)


def build_inline_keyboard(options: list[dict], ask_id: str, item_index: int) -> list[list[dict]]:
    """한 질문의 옵션 → 인라인 키보드 행(옵션당 1행).
    callback_data = "a:<ask_id>:<item_index>:<opt_index>" (64바이트 이내).
    """
    rows: list[list[dict]] = []
    for oi, opt in enumerate(options):
        label = (opt.get("label") or f"opt{oi}").strip() or f"opt{oi}"
        cb = f"a:{ask_id}:{item_index}:{oi}"
        rows.append([{"text": label, "callback_data": cb}])
    return rows


def parse_callback(callback_data: str) -> tuple[str, int, int] | None:
    """callback_data = "a:<ask_id>:<item_index>:<opt_index>" → (ask_id, item, opt).
    불일치/잘못된 인덱스 → None.
    """
    if not callback_data or not callback_data.startswith("a:"):
        return None
    parts = callback_data.split(":")
    if len(parts) != 4:
        return None
    try:
        return parts[1], int(parts[2]), int(parts[3])
    except ValueError:
        return None
