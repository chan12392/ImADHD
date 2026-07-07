"""Settings.route_all_asks 로드 단위 테스트.

기본 True(터미널 직접 세션의 AskUserQuestion 도 텔레그램 inline 버튼으로 라우팅).
IMADHD_ROUTE_ALL_ASKS 가 명시적 off 값(0/false/no/off)일 때만 False.
"""
from __future__ import annotations

import pytest

from imadhd.config import Settings


def _load(env: dict, tmp_path, monkeypatch) -> Settings:
    """IMADHD_ENV_FILE 로 테스트 env 격리. data_dir 도 tmp 로."""
    full = dict(env)
    full.setdefault("IMADHD_DATA_DIR", str(tmp_path / "data"))
    env_file = tmp_path / "env"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in full.items()), encoding="utf-8")
    monkeypatch.setenv("IMADHD_ENV_FILE", str(env_file))
    return Settings.load()


_BASE = {"TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_ALLOWED_CHAT_ID": "123456"}


def test_default_true(tmp_path, monkeypatch):
    """키 미지정 → 기본 True(대표님 요구: 터미널 세션 질문도 텔레그램으로)."""
    s = _load(_BASE, tmp_path, monkeypatch)
    assert s.route_all_asks is True


@pytest.mark.parametrize("off", ["0", "false", "no", "off", "FALSE", " No "])
def test_explicit_off_is_false(off, tmp_path, monkeypatch):
    """명시적 off 값 → False. 대소문자/공백 무시."""
    env = dict(_BASE, IMADHD_ROUTE_ALL_ASKS=off)
    s = _load(env, tmp_path, monkeypatch)
    assert s.route_all_asks is False


@pytest.mark.parametrize("on", ["1", "true", "yes", "", "anything-else"])
def test_non_off_is_true(on, tmp_path, monkeypatch):
    """off 집합 외 값/빈값 → True(기본 on 의미 보존)."""
    env = dict(_BASE, IMADHD_ROUTE_ALL_ASKS=on)
    s = _load(env, tmp_path, monkeypatch)
    assert s.route_all_asks is True
