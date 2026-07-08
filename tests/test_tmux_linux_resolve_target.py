"""tmux_linux transport 의 세션별 타겟 해석 단위 테스트.
실제 tmux 프로세스 호출 없이 _resolve_target() 순수 로직만 검증."""
import importlib

import imadhd.transports.tmux_linux as tl
from imadhd.transports.tmux_linux import _resolve_target, TMUX_TARGET


def test_resolve_target_uses_session_pane_when_present():
    assert _resolve_target({"tmux_pane": "%7"}) == "%7"


def test_resolve_target_falls_back_to_default_when_missing():
    assert _resolve_target({}) == TMUX_TARGET


def test_resolve_target_falls_back_when_empty_string():
    assert _resolve_target({"tmux_pane": ""}) == TMUX_TARGET


def test_resolve_target_falls_back_when_none_target():
    assert _resolve_target(None) == TMUX_TARGET


def test_default_prefix_is_claude_neutral(monkeypatch):
    """IMADHD_TMUX_PREFIX 미설정 시 중립 기본값 'claude' (2026-07-08).

    특정 배포 전용 명명이 폴백 타겟 기본값이면 OSS 사용자에게 혼란.
    """
    monkeypatch.delenv("IMADHD_TMUX_PREFIX", raising=False)
    importlib.reload(tl)
    try:
        assert tl.TMUX_TARGET == "claude"
        assert tl._resolve_target({}) == "claude"
    finally:
        # 다른 테스트가 모듈 전역값에 의존하므로 복원.
        importlib.reload(tl)


def test_prefix_env_override(monkeypatch):
    """IMADHD_TMUX_PREFIX=custom 시 기존 세션명 유지 (마이그레이션 경로)."""
    monkeypatch.setenv("IMADHD_TMUX_PREFIX", "mybot")
    importlib.reload(tl)
    try:
        assert tl.TMUX_TARGET == "mybot"
    finally:
        monkeypatch.delenv("IMADHD_TMUX_PREFIX", raising=False)
        importlib.reload(tl)
