"""/list 명령: 창 제목 표시(대표님 요청 — PID/경로 대신 창 제목). hwnd 무효 시 cwd 폴백."""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.list_command import ListCommand


class FakeInfo:
    def __init__(self, number, hwnd, pid, cwd):
        self.number, self.hwnd, self.pid, self.cwd = number, hwnd, pid, cwd


class FakeRegistry:
    def __init__(self, items):
        self._items = items

    def active(self):
        return self._items


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def test_list_empty():
    tg = FakeTelegram()
    ctx = CommandContext(settings=None, registry=FakeRegistry([]), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    assert tg.sent == ["활성 터미널 없음"]


def test_list_shows_window_title_not_pid(monkeypatch):
    import imadhd.commands.list_command as lc
    monkeypatch.setattr(lc, "window_title", lambda hwnd: "Claude Code — myproj")
    tg = FakeTelegram()
    items = [FakeInfo(1, hwnd=111, pid=222, cwd="C:/work/myproj")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    line = tg.sent[0]
    assert "Claude Code — myproj" in line
    assert "222" not in line          # PID 더 이상 안 뜸
    assert "C:/work/myproj" not in line


def test_list_falls_back_to_cwd_when_title_empty(monkeypatch):
    import imadhd.commands.list_command as lc
    monkeypatch.setattr(lc, "window_title", lambda hwnd: "")
    tg = FakeTelegram()
    items = [FakeInfo(2, hwnd=0, pid=333, cwd="C:/work/other")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    assert "C:/work/other" in tg.sent[0]
