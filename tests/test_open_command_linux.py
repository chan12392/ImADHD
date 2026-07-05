"""/open 의 Linux(tmux) 분기 단위 테스트. subprocess/시간 mock, 실제 tmux 호출 없음."""
from imadhd.commands.base import CommandContext, Message
import imadhd.commands.open_command as oc


class _FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def _handle_linux(monkeypatch, text, fixed_time=1783300000):
    monkeypatch.setattr(oc.os, "name", "posix")
    monkeypatch.setattr(oc.time, "time", lambda: fixed_time)
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    tg = _FakeTelegram()
    ctx = CommandContext(settings=None, registry=None, transport=None, telegram=tg)
    oc.OpenCommand().handle(Message("1", text, {}), ctx)
    return captured, tg


def test_linux_open_bare_creates_named_tmux_session(monkeypatch):
    captured, tg = _handle_linux(monkeypatch, "/open")
    assert captured["args"][:4] == ["tmux", "new-session", "-d", "-s"]
    assert captured["args"][4] == "claude-1783300000"
    assert "claude" in captured["args"][5]
    assert "claude-1783300000" in tg.sent[-1]


def test_linux_open_model_arg_passed_to_launch_cmd(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open opus")
    assert "--model opus" in captured["args"][5]


def test_linux_open_glm_keeps_proxy_env_in_launch_cmd(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    captured, _ = _handle_linux(monkeypatch, "/open glm")
    assert "ANTHROPIC_BASE_URL" in captured["args"][5]


def test_linux_open_default_strips_proxy_env_from_launch_cmd(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "ANTHROPIC_BASE_URL" not in captured["args"][5]
