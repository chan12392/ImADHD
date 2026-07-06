"""/list 명령: 이름 우선순위 label > ai-title > HH:MM + status."""
from imadhd.commands import list_command as lc
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.list_command import ListCommand


class FakeInfo:
    def __init__(self, number, started_at="", status="idle", label="",
                 hwnd=0, pid=0, cwd="", session_id=""):
        self.number = number
        self.started_at = started_at
        self.status = status
        self.label = label
        self.hwnd = hwnd
        self.pid = pid
        self.cwd = cwd
        self.session_id = session_id


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


def test_list_shows_label_when_set(monkeypatch):
    # 라벨 있으면 ai-title 무시(수동 우선)
    monkeypatch.setattr(lc, "read_ai_title", lambda *a: "무시돼야할 ai-title")
    tg = FakeTelegram()
    items = [FakeInfo(1, started_at="2026-07-07T14:32:00", status="busy", label="디버깅")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    line = tg.sent[0]
    assert "디버깅" in line
    assert "📝" in line
    assert "#1" in line
    assert "무시돼야할" not in line


def test_list_shows_ai_title_when_no_label(monkeypatch):
    # 라벨 없고 ai-title 있으면 ai-title
    monkeypatch.setattr(lc, "read_ai_title", lambda *a: "ImADHD close 버그 수정")
    tg = FakeTelegram()
    items = [FakeInfo(2, started_at="2026-07-07T09:05:00", status="idle",
                      cwd="C:\\Users\\chan1", session_id="abc123")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    line = tg.sent[0]
    assert "ImADHD close 버그 수정" in line
    assert "09:05" not in line   # 시간 폴백 안 됨


def test_list_shows_time_when_no_label_no_ai_title(monkeypatch):
    monkeypatch.setattr(lc, "read_ai_title", lambda *a: "")
    tg = FakeTelegram()
    items = [FakeInfo(2, started_at="2026-07-07T09:05:00", status="idle", label="")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    line = tg.sent[0]
    assert "09:05" in line
    assert "⭕" in line


def test_list_busy_emoji(monkeypatch):
    monkeypatch.setattr(lc, "read_ai_title", lambda *a: "")
    tg = FakeTelegram()
    items = [FakeInfo(3, started_at="2026-07-07T14:32:00", status="busy", label="")]
    ctx = CommandContext(settings=None, registry=FakeRegistry(items), transport=None, telegram=tg)
    ListCommand().handle(Message("1", "/list", {}), ctx)
    assert "📝" in tg.sent[0]
