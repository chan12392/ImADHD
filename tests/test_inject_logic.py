from imadhd.commands.base import Message, CommandContext
from imadhd.commands.inject_command import InjectCommand
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


class FakeSettings:
    reply_marker = "텔레그램으로 답변"


def test_inject_dead_terminal_releases_slot(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=False)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    cmd = InjectCommand()
    cmd.handle(Message("42", "1️⃣ hi", {}), ctx)
    assert tr.injected is None                       # not injected
    assert reg.get(1) is None                         # slot released
    assert any("꺼짐" in t for _, t in tg.sent)


def test_inject_alive_injects_with_marker(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "1️⃣ do work", {}), ctx)
    assert tr.injected is not None
    _, text = tr.injected
    assert "do work" in text and "텔레그램으로 답변" in text
    assert any("📩" in t for _, t in tg.sent)


def test_inject_unknown_number(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "5️⃣ hi", {}), ctx)
    assert tr.injected is None
    assert any("없음" in t for _, t in tg.sent)
