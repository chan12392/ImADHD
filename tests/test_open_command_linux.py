"""/open 의 Linux(tmux) 분기 단위 테스트 (2026-07-06 단일화).

/open 단일 명령만: 모델/glm 변형 제거. 항상 기본 claude + 홈 cwd.
"""
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
    # debounce 모듈 변수 리셋(연속 테스트 시 직전 /open 잔재로 스킵 방지).
    monkeypatch.setattr(oc, "_LAST_OPEN_MONO", 0.0)
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


def test_linux_open_uses_home_cwd(monkeypatch):
    """/open 단일화: cd $HOME 에서 claude 실행."""
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert 'cd "$HOME"' in captured["args"][5]


def test_linux_open_does_not_source_proxy_env(monkeypatch):
    """/open 단일화: z.ai 프록시 env 파일 source 안 함(공식 Anthropic)."""
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "anthropic.env" not in captured["args"][5]


def test_linux_open_no_model_flag(monkeypatch):
    """/open 단일화: --model 인자 없음."""
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "--model" not in captured["args"][5]


def test_linux_open_no_skip_perms_by_default(monkeypatch):
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "--dangerously-skip-permissions" not in captured["args"][5]


def test_linux_open_skip_perms_env_opt_in(monkeypatch):
    monkeypatch.setenv("IMADHD_SKIP_PERMS", "1")
    captured, _ = _handle_linux(monkeypatch, "/open")
    assert "--dangerously-skip-permissions" in captured["args"][5]


def test_linux_open_variants_do_not_match():
    """/open 단일만. 변형은 match() 에서 미매치(router 가 실행 안 함)."""
    c = oc.OpenCommand()
    for txt in ["/open opus", "/open glm", "/open $(touch /tmp/pwn)", "/open 1"]:
        assert not c.match(Message("1", txt, {})), f"{txt} 는 매치되면 안 됨"
