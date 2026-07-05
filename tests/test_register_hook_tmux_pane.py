"""register_hook 의 tmux_pane 캡처(Linux 전용) 단위 테스트."""
from imadhd.hooks.register_hook import _capture_tmux_pane


def test_capture_tmux_pane_present(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%7")
    assert _capture_tmux_pane() == "%7"


def test_capture_tmux_pane_absent(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert _capture_tmux_pane() == ""
