"""transcript.read_ai_title 단위: 임시 jsonl 경계 케이스."""
import json
from pathlib import Path

from imadhd.core import transcript as tr


def test_encode_cwd():
    assert tr.encode_cwd("C:\\Users\\chan1") == "C--Users-chan1"
    assert tr.encode_cwd("") == ""
    assert tr.encode_cwd("C:/x y") == "C--x-y"


def _write(p: Path, records):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_read_ai_title_basic(tmp_path):
    sid = "abc-123"
    p = tmp_path / "projects" / "C--Users-chan1" / f"{sid}.jsonl"
    _write(p, [
        {"type": "user", "message": "..."},
        {"type": "ai-title", "aiTitle": "close 버그 수정", "sessionId": sid},
    ])
    assert tr.read_ai_title(sid, "C:\\Users\\chan1", claude_home=tmp_path) == "close 버그 수정"


def test_read_ai_title_missing_file(tmp_path):
    assert tr.read_ai_title("nope", "C:\\Users\\chan1", claude_home=tmp_path) == ""


def test_read_ai_title_no_title_record(tmp_path):
    # 첫 응답 전: ai-title 레코드 없음
    sid = "x"
    p = tmp_path / "projects" / "C--Users-chan1" / f"{sid}.jsonl"
    _write(p, [{"type": "user", "message": "..."}, {"type": "assistant", "content": "..."}])
    assert tr.read_ai_title(sid, "C:\\Users\\chan1", claude_home=tmp_path) == ""


def test_read_ai_title_last_wins(tmp_path):
    # 세션 진행中 갱신 → 마지막 ai-title 이 최신
    sid = "x"
    p = tmp_path / "projects" / "C--Users-chan1" / f"{sid}.jsonl"
    _write(p, [
        {"type": "ai-title", "aiTitle": "초기 제목", "sessionId": sid},
        {"type": "user", "message": "..."},
        {"type": "ai-title", "aiTitle": "갱신된 제목", "sessionId": sid},
    ])
    assert tr.read_ai_title(sid, "C:\\Users\\chan1", claude_home=tmp_path) == "갱신된 제목"


def test_read_ai_title_empty_session(tmp_path):
    assert tr.read_ai_title("", "C:\\Users\\chan1", claude_home=tmp_path) == ""


def test_read_ai_title_truncates(tmp_path):
    sid = "x"
    p = tmp_path / "projects" / "C--Users-chan1" / f"{sid}.jsonl"
    long_title = "가" * 100
    _write(p, [{"type": "ai-title", "aiTitle": long_title, "sessionId": sid}])
    out = tr.read_ai_title(sid, "C:\\Users\\chan1", claude_home=tmp_path)
    assert len(out) == 60
