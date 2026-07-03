"""Settings.load 보안 검증(fail-closed).

공개 봇: 토큰만 있으면 누구나 터미널 제어 가능 → TELEGRAM_ALLOWED_CHAT_ID 필수.
빠뜨리면 기동 거부(RuntimeError). IMADHD_ALLOW_ANY_CHAT=1 은 dev 옵트인.
"""
from __future__ import annotations

import pytest

# Settings.load 가 읽는 모든 env 키(테스트 격리).
_ENV_KEYS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID",
             "IMADHD_ALLOW_ANY_CHAT", "IMADHD_DATA_DIR"]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """실제 환경변수/.env 오염 차단. env_path=tmp 빈파일 → load_dotenv 가 cwd/.env 안 읽음."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IMADHD_DATA_DIR", str(tmp_path))   # 실제 ~/.imadhd 오염 방지
    return tmp_path / ".env"   # 빈 경로(load 시 존재 여부 무관, load_dotenv 가 무해)


def test_token_and_chat_id_ok(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "123456789")
    from imadhd.config import Settings
    s = Settings.load(env_path=clean_env)
    assert s.bot_token == "123:abc"
    assert s.allowed_chat_id == "123456789"
    assert s.allow_any_chat is False


def test_missing_chat_id_rejected(clean_env, monkeypatch):
    """핵심: 토큰만 있고 chat_id 없으면 기동 거부(fail-closed)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    # TELEGRAM_ALLOWED_CHAT_ID, IMADHD_ALLOW_ANY_CHAT 둘 다 없(clean_env)
    from imadhd.config import Settings
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_CHAT_ID required"):
        Settings.load(env_path=clean_env)


def test_allow_any_chat_opt_in(clean_env, monkeypatch):
    """dev 옵트인: chat_id 없어도 IMADHD_ALLOW_ANY_CHAT=1 이면 기동."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("IMADHD_ALLOW_ANY_CHAT", "1")
    from imadhd.config import Settings
    s = Settings.load(env_path=clean_env)
    assert s.allowed_chat_id is None
    assert s.allow_any_chat is True


@pytest.mark.parametrize("val", ["true", "TRUE", "yes", "1"])
def test_allow_any_truthy_variants(clean_env, monkeypatch, val):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("IMADHD_ALLOW_ANY_CHAT", val)
    from imadhd.config import Settings
    assert Settings.load(env_path=clean_env).allow_any_chat is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "random"])
def test_allow_any_falsy_variants_reject(clean_env, monkeypatch, val):
    """ALLOW_ANY=0/false/no/빈값 → 옵트인 아님 → chat_id 없으면 거부."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("IMADHD_ALLOW_ANY_CHAT", val)
    from imadhd.config import Settings
    with pytest.raises(RuntimeError):
        Settings.load(env_path=clean_env)


def test_missing_token_rejected(clean_env):
    """토큰 없으면 token 에러가 chat_id 체크보다 먼저."""
    from imadhd.config import Settings
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN missing"):
        Settings.load(env_path=clean_env)
