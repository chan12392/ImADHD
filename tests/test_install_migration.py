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
