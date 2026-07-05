"""tmux_linux transport 의 세션별 타겟 해석 단위 테스트.
실제 tmux 프로세스 호출 없이 _resolve_target() 순수 로직만 검증."""
from imadhd.transports.tmux_linux import _resolve_target, TMUX_TARGET


def test_resolve_target_uses_session_pane_when_present():
    assert _resolve_target({"tmux_pane": "%7"}) == "%7"


def test_resolve_target_falls_back_to_default_when_missing():
    assert _resolve_target({}) == TMUX_TARGET


def test_resolve_target_falls_back_when_empty_string():
    assert _resolve_target({"tmux_pane": ""}) == TMUX_TARGET


def test_resolve_target_falls_back_when_none_target():
    assert _resolve_target(None) == TMUX_TARGET
