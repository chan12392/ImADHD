"""perm_manager 단위 테스트 (callback 파싱 + 원자적 record 저장).

ask_manager 와 구조 동일 — p: prefix 분기 검증.
"""
import json

from imadhd.core import perm_manager


def test_new_perm_id_is_12_hex():
    pid = perm_manager.new_perm_id()
    assert len(pid) == 12
    assert all(c in "0123456789abcdef" for c in pid)


def test_write_load_roundtrip(tmp_path):
    rec = {
        "perm_id": "abc123def456", "session_id": "s", "chat_id": "1", "slot": 1,
        "tool_name": "Bash", "summary": "rm -rf build/", "message_id": 42,
        "created_at": "2026-07-06T00:00:00", "status": "pending", "answer": None,
    }
    perm_manager.write_record(tmp_path, rec)
    loaded = perm_manager.load_record(tmp_path, "abc123def456")
    assert loaded == rec


def test_load_missing_returns_none(tmp_path):
    assert perm_manager.load_record(tmp_path, "nope") is None


def test_build_inline_keyboard_yes_no():
    kb = perm_manager.build_inline_keyboard("pid1")
    assert len(kb) == 1                # 단일 행
    assert len(kb[0]) == 2             # Yes/No 2버튼
    texts = {b["text"] for b in kb[0]}
    assert any("승인" in t for t in texts)
    assert any("거부" in t for t in texts)
    cbs = {b["callback_data"] for b in kb[0]}
    assert "p:pid1:yes" in cbs
    assert "p:pid1:no" in cbs


def test_parse_callback_valid():
    assert perm_manager.parse_callback("p:pid1:yes") == ("pid1", "yes")
    assert perm_manager.parse_callback("p:pid1:no") == ("pid1", "no")


def test_parse_callback_rejects_invalid():
    # ask prefix(a:), 잘못된 choice, 파트 수 안 맞음, 빈 값
    assert perm_manager.parse_callback("a:pid1:0:1") is None
    assert perm_manager.parse_callback("p:pid1:maybe") is None
    assert perm_manager.parse_callback("p:pid1") is None
    assert perm_manager.parse_callback("p:pid1:yes:extra") is None
    assert perm_manager.parse_callback("") is None
    assert perm_manager.parse_callback("garbage") is None


def test_write_is_atomic_no_tmp_residue(tmp_path):
    """원자 쓰기: .tmp 잔재 없음 + perms/ 디렉토리 자동 생성."""
    # perm_manager 가 data_dir/perms/<id>.json 구조 → data_dir=tmp_path 넘기면
    # tmp/perms/ 가 자동 생성되는지 검증.
    rec = {"perm_id": "x", "status": "pending", "answer": None}
    perm_manager.write_record(tmp_path, rec)
    assert (tmp_path / "perms" / "x.json").exists()
    assert not any(p.suffix == ".tmp" for p in (tmp_path / "perms").iterdir())
