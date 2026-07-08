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
            stdout = "mybot-1783300000\n"
        return _R()

    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    reg = FakeRegistry({2: FakeInfo(2, tmux_pane="%7")})
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=reg, transport=None, telegram=tg)
    cc.CloseCommand().handle(Message("1", "/close 2", {}), ctx)

    assert calls[0] == ["tmux", "display-message", "-p", "-t", "%7", "#S"]
    assert calls[1] == ["tmux", "kill-session", "-t", "mybot-1783300000"]
    assert reg.released == [2]
    assert "종료" in tg.sent[-1]


def test_linux_close_no_tmux_pane_falls_back_to_prefix_session(monkeypatch):
    """/close: tmux_pane 빈 슬롯(구버전/resume/수동 세션)도 폴백 타겟으로 kill.

    2026-07-08: 이전엔 tmux_pane 빈 슬롯이 posix 분기를 안 타 killed=False →
    좀비 tmux 세션 잔존. 이제 IMADHD_TMUX_PREFIX 세션(기본 'claude')으로
    kill-session 시도 → 슬롯도 해제 + 세션도 종료.
    """
    monkeypatch.setattr(cc.os, "name", "posix")
    monkeypatch.delenv("IMADHD_TMUX_PREFIX", raising=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class _R:
            returncode = 0
            stdout = ""
        return _R()

    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    reg = FakeRegistry({3: FakeInfo(3, tmux_pane="")})
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=reg, transport=None, telegram=tg)
    cc.CloseCommand().handle(Message("1", "/close 3", {}), ctx)

    # 폴백 타겟(IMADHD_TMUX_PREFIX 기본 'claude')으로 kill-session 1회 시도.
    assert ["tmux", "kill-session", "-t", "claude"] in calls
    assert reg.released == [3]
    assert "종료" in tg.sent[-1]


def test_linux_close_no_tmux_pane_kill_fails_releases_only(monkeypatch):
    """/close: 폴백 kill-session 이 예외(세션 없음/권한)로 실패해도 슬롯은 해제 + 실패 안내.

    close_command 코드는 kill-session 의 returncode 가 아닌 예외 발생 여부로
    실패를 판정한다(subprocess.run 자체가 안 죽으면 killed=True). 그래서 이
    테스트는 kill-session 호출이 예외를 던지는 케이스를 시뮬레이션한다.
    """
    monkeypatch.setattr(cc.os, "name", "posix")
    monkeypatch.delenv("IMADHD_TMUX_PREFIX", raising=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        # kill-session 호출만 예외로(폴백 경로에선 display-message 안 타므로
        # 모든 호출이 kill-session 이라 단순하게 예외 처리).
        raise subprocess.TimeoutExpired(cmd=args, timeout=10)

    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    reg = FakeRegistry({3: FakeInfo(3, tmux_pane="")})
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=reg, transport=None, telegram=tg)
    cc.CloseCommand().handle(Message("1", "/close 3", {}), ctx)

    assert ["tmux", "kill-session", "-t", "claude"] in calls
    assert reg.released == [3]
    assert "실패" in tg.sent[-1]
