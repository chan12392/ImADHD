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
    assert any("종료" in t for _, t in tg.sent)


def test_inject_alive_injects_with_marker(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "1️⃣ do work", {}), ctx)
    assert tr.injected is not None
    _, text = tr.injected
    assert "do work" in text and "[텔레그램에서 온 요청]" in text
    assert "\n" not in text                           # 한 줄 주입 (분할 방지)


def test_inject_unknown_number(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "5️⃣ hi", {}), ctx)
    assert tr.injected is None
    assert any("없음" in t for _, t in tg.sent)


def test_button_click_sets_pending_no_inject(tmp_path):
    """ReplyKeyboard 버튼 클릭(번호+상태마크) → 선택모드 pending. 주입X, 안내 생략."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "1️⃣.⭕", {}), ctx)
    assert tr.injected is None              # 주입 안 됨
    assert tg.sent == []                    # 안내 메시지 생략
    assert ctx.pending.get("42", (None,))[0] == 1


def test_button_click_same_again_cancels(tmp_path):
    """같은 번호 재클릭 → 대기 취소."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "1️⃣.⭕", {}), ctx)
    assert ctx.pending["42"][0] == 1
    InjectCommand().handle(Message("42", "1️⃣.⭕", {}), ctx)   # 같은 번호 → 취소
    assert "42" not in ctx.pending


def test_button_click_different_switches(tmp_path):
    """다른 번호 클릭 → 대기 번호 교체."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "1️⃣.⭕", {}), ctx)
    InjectCommand().handle(Message("42", "2️⃣.⭕", {}), ctx)   # 다른 번호 → 교체
    assert ctx.pending["42"][0] == 2


def test_do_inject_consumes_body(tmp_path):
    """router pending 본문 주입 경로(do_inject) 검증."""
    from imadhd.commands.inject_command import do_inject
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    do_inject(ctx, 1, "안녕 백호", "42")
    assert tr.injected is not None
    _, text = tr.injected
    assert "안녕 백호" in text and "[텔레그램에서 온 요청]" in text
