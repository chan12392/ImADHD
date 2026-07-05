"""step3_hooks() 마이그레이션 단위 테스트.

예전 설치가 settings.json global env 에 넣어둔 TELEGRAM_BOT_TOKEN /
TELEGRAM_ALLOWED_CHAT_ID 를 제거하고, env 블록이 비면 키 자체를 정리하는지.
실제 ~/.claude/settings.json 대신 임시 파일로 검증 (monkeypatch)."""
import json

import imadhd.install as inst


def _run_step3(tmp_path, monkeypatch, initial_settings: dict) -> dict:
    """임시 CLAUDE_DIR/SETTINGS_FILE 로 step3_hooks 실행 후 저장된 JSON 반환."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(json.dumps(initial_settings, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(inst, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(inst, "SETTINGS_FILE", settings)
    inst.step3_hooks(token="dummy-token", chat="123")
    return json.loads(settings.read_text(encoding="utf-8"))


def test_migration_strips_telegram_keys_from_global_env(tmp_path, monkeypatch):
    initial = {
        "env": {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_ALLOWED_CHAT_ID": "123456789",
            "SOME_OTHER": "keep-me",
        },
        "hooks": {},
    }
    out = _run_step3(tmp_path, monkeypatch, initial)
    env = out.get("env", {})
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "TELEGRAM_ALLOWED_CHAT_ID" not in env
    # 다른 env 키는 보존
    assert env.get("SOME_OTHER") == "keep-me"


def test_migration_drops_empty_env_block(tmp_path, monkeypatch):
    initial = {
        "env": {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_ALLOWED_CHAT_ID": "123456789",
        },
        "hooks": {},
    }
    out = _run_step3(tmp_path, monkeypatch, initial)
    # TELEGRAM 키만 있었으므로 제거 후 env 비면 키 자체 삭제
    assert "env" not in out


def test_migration_idempotent_no_env_block(tmp_path, monkeypatch):
    # 신규 설치: env 블록 자체 없음 → 마이그레이션 no-op
    initial = {"hooks": {}}
    out = _run_step3(tmp_path, monkeypatch, initial)
    assert "env" not in out
    # 훅 4개 추가됨
    assert "SessionStart" in out["hooks"]
    assert "Stop" in out["hooks"]


def test_migration_preserves_non_token_env(tmp_path, monkeypatch):
    initial = {
        "env": {"MY_THING": "x", "PATH_EXTRA": "y"},
        "hooks": {},
    }
    out = _run_step3(tmp_path, monkeypatch, initial)
    assert out.get("env") == {"MY_THING": "x", "PATH_EXTRA": "y"}


def test_backup_file_is_redacted(tmp_path, monkeypatch):
    """백업 파일에 토큰 잔류 금지 — 마이그레이션(redaction) 후 백업."""
    initial = {
        "env": {"TELEGRAM_BOT_TOKEN": "123456:ABC-SECRET", "TELEGRAM_ALLOWED_CHAT_ID": "999"},
        "hooks": {},
    }
    _run_step3(tmp_path, monkeypatch, initial)
    baks = list((tmp_path / ".claude").glob("settings.json.bak-*"))
    assert baks, "백업 파일 생성돼야 함"
    bak_text = baks[0].read_text(encoding="utf-8")
    assert "123456:ABC-SECRET" not in bak_text
    assert "TELEGRAM_BOT_TOKEN" not in bak_text
    assert "TELEGRAM_ALLOWED_CHAT_ID" not in bak_text


def test_scrub_token_lines_masks_json_values():
    """_scrub_token_lines 가 JSON 폼의 TELEGRAM 시크릿 값을 마스킹."""
    raw = '{"env": {"TELEGRAM_BOT_TOKEN": "999:REAL-SECRET", "TELEGRAM_ALLOWED_CHAT_ID": "111222333"}}'
    out = inst._scrub_token_lines(raw)
    assert "999:REAL-SECRET" not in out
    assert "111222333" not in out
    assert "<redacted>" in out


def test_scrub_token_lines_covers_unquoted_and_dotenv():
    """unquoted(JSON 숫자) · dotenv KEY=value 폼도 마스킹 (이전 quoted 전용 회귀)."""
    cases = [
        # JSON unquoted (숫자 chat id)
        '{"TELEGRAM_ALLOWED_CHAT_ID":111222333,"TELEGRAM_BOT_TOKEN":999:ABC}',
        # dotenv
        'TELEGRAM_BOT_TOKEN=999:ABC\nTELEGRAM_ALLOWED_CHAT_ID=111222333\n',
    ]
    for raw in cases:
        out = inst._scrub_token_lines(raw)
        assert "111222333" not in out, f"unquoted/dotenv 값 잔류: {out}"
        assert "999:ABC" not in out, f"unquoted/dotenv 값 잔류: {out}"
        assert "<redacted>" in out


def test_load_settings_parse_fail_scrubs_bad_backup(tmp_path, monkeypatch):
    """settings.json malformed/BOM → .bad-* 백업에 토큰 잔류 금지 + 원본 삭제."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    # BOM 으로 JSON parse 실패 유도 + 토큰 포함
    settings.write_text(
        '﻿{"env": {"TELEGRAM_BOT_TOKEN": "999:REAL-SECRET", '
        '"TELEGRAM_ALLOWED_CHAT_ID": "111222333"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(inst, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(inst, "SETTINGS_FILE", settings)
    data = inst._load_settings()
    assert data == {}  # parse 실패 → 빈 dict
    assert not settings.exists()  # 원본 삭제
    baks = list(claude_dir.glob("settings.json.bad-*"))
    assert baks, "parse-fail 백업 생성돼야 함"
    bak_text = baks[0].read_text(encoding="utf-8", errors="replace")
    assert "999:REAL-SECRET" not in bak_text
    assert "111222333" not in bak_text
    assert "<redacted>" in bak_text
