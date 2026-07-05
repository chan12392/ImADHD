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
    assert captured["args"][4] == "chleo-1783300000"
    assert "claude" in captured["args"][5]
    assert "chleo-1783300000" in tg.sent[-1]


def test_linux_open_model_arg_passed_to_launch_cmd(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open opus")
    assert "--model opus" in captured["args"][5]


def test_linux_open_glm_sources_anthropic_env_file(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open glm")
    # GLM 토큰은 bash export(커맨드라인/ps 노출) 대신 0600 env 파일 source 로 주입.
    assert "source $HOME/.anthropic.env" in captured["args"][5]
    assert "export ANTHROPIC_" not in captured["args"][5]


def test_linux_open_default_does_not_source_proxy_env(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open")
    # GLM 아닐 땐 anthropic.env source 안 함 (공식 Anthropic = ~/.claude 자격증명).
    assert "anthropic.env" not in captured["args"][5]


def test_linux_open_rejects_shell_injection_in_model(monkeypatch):
    captured, tg = _handle_linux(monkeypatch, "/open $(touch /tmp/pwn)")
    # 모델명 검증 실패 → tmux 실행 안 함
    assert "args" not in captured
    assert any("허용되지 않는 문자" in t for t in tg.sent)


def test_linux_open_no_skip_perms_by_default(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "--dangerously-skip-permissions" not in captured["args"][5]


def test_linux_open_skip_perms_env_opt_in(monkeypatch):
    monkeypatch.setenv("IMADHD_SKIP_PERMS", "1")
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "--dangerously-skip-permissions" in captured["args"][5]
