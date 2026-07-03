"""/new N 핸들러 단위 테스트. N번 터미널에 /clear 주입 + idle 환원."""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.new_command import NewCommand
from imadhd.core.registry import JSONFileRegistry


class FakeTransport:
    def __init__(self, alive):
        self._alive = alive
        self.injected = None
    def is_alive(self, target):
        return self._alive
    def inject(self, target, text, background=False):
        self.injected = (target, text)


class FakeTG:
    def __init__(self):
        self.sent = []
    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


def _ctx(reg, alive):
    return CommandContext(settings=None, registry=reg, transport=FakeTransport(alive), telegram=FakeTG())


def test_new_match_variants():
    c = NewCommand()
    for t in ["/new 1", "/new", "/NEW 2", "/새대화 3", "/초기화 1"]:
        assert c.match(Message("1", t, {})) is True, t


def test_new_no_match():
    c = NewCommand()
    for t in ["/list", "/help", "1️⃣", "hi", "/news 1"]:
        assert c.match(Message("1", t, {})) is False, t


def test_new_clears_alive_slot(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    ctx = _ctx(reg, True)
    NewCommand().handle(Message("9", "/new 1", {}), ctx)
    assert ctx.transport.injected is not None
    assert ctx.transport.injected[1] == "/clear"        # 마커 없이 /clear 단독
    assert reg.get(1).status == "idle"
    assert any("새 대화" in t for _, t in ctx.telegram.sent)


def test_new_no_arg_shows_usage(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    ctx = _ctx(reg, True)
    NewCommand().handle(Message("9", "/new", {}), ctx)
    assert ctx.transport.injected is None
    assert any("사용법" in t for _, t in ctx.telegram.sent)


def test_new_bad_arg_shows_usage(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    ctx = _ctx(reg, True)
    NewCommand().handle(Message("9", "/new abc", {}), ctx)
    assert ctx.transport.injected is None
    assert any("사용법" in t for _, t in ctx.telegram.sent)


def test_new_unknown_slot(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    ctx = _ctx(reg, True)
    NewCommand().handle(Message("9", "/new 5", {}), ctx)
    assert ctx.transport.injected is None
    assert any("없음" in t for _, t in ctx.telegram.sent)


def test_new_dead_releases_slot(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    ctx = _ctx(reg, False)
    NewCommand().handle(Message("9", "/new 1", {}), ctx)
    assert ctx.transport.injected is None
    assert reg.get(1) is None                          # slot released
    assert any("종료" in t for _, t in ctx.telegram.sent)
