"""/close 의 Linux(tmux) 분기 단위 테스트."""
from imadhd.commands.base import CommandContext, Message
import imadhd.commands.close_command as cc


class FakeInfo:
    def __init__(self, number=2, tmux_pane="%7"):
        self.number = number
        self.hwnd = 0
        self.pid = 0
        self.tmux_pane = tmux_pane


class FakeRegistry:
    def __init__(self, infos):
        self._infos = infos
        self.released = []

    def get(self, n):
        return self._infos.get(n)

    def release(self, n):
        self.released.append(n)
        return True


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def test_linux_close_kills_tmux_session(monkeypatch):
    """/close 는 tmux pane → session name 조회 → kill-session (대표님 2026-07-07)."""
    monkeypatch.setattr(cc.os, "name", "posix")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class _R:
            returncode = 0
            stdout = "claude-1783300000\n"
        return _R()

    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    reg = FakeRegistry({2: FakeInfo(2, tmux_pane="%7")})
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=reg, transport=None, telegram=tg)
    cc.CloseCommand().handle(Message("1", "/close 2", {}), ctx)

    assert calls[0] == ["tmux", "display-message", "-p", "-t", "%7", "#S"]
    assert calls[1] == ["tmux", "kill-session", "-t", "claude-1783300000"]
    assert reg.released == [2]
    assert "종료" in tg.sent[-1]


def test_linux_close_no_tmux_pane_releases_only(monkeypatch):
    """/close: tmux_pane 없으면 kill 못 하지만 슬롯은 해제 + 실패 안내."""
    monkeypatch.setattr(cc.os, "name", "posix")
    calls = []
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: calls.append(a))
    reg = FakeRegistry({3: FakeInfo(3, tmux_pane="")})
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=reg, transport=None, telegram=tg)
    cc.CloseCommand().handle(Message("1", "/close 3", {}), ctx)

    assert calls == []  # tmux_pane 없으면 tmux 호출 자체 안 함
    assert reg.released == [3]
    assert "실패" in tg.sent[-1]
