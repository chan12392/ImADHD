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
    reply_marker = "[A.D.H.D]"
    data_dir = None  # 각 테스트에서 tmp_path 로 주입(마커 플래그 파일 경로용)


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
    assert "do work" in text and "[A.D.H.D]" in text
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
    assert "안녕 백호" in text and "[A.D.H.D]" in text


def test_slash_injects_body(tmp_path):
    """/N<본문> → 즉시 주입 (이모지 흐름과 동일)."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    cmd = InjectCommand()
    assert cmd.match(Message("42", "/1 do work", {})) is True
    cmd.handle(Message("42", "/1 do work", {}), ctx)
    assert tr.injected is not None
    _, text = tr.injected
    assert "do work" in text and "[A.D.H.D]" in text


def test_slash_no_space_injects(tmp_path):
    """/1본문 (공백 없음) → 본문 주입."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "/1빌드확인", {}), ctx)
    assert tr.injected is not None
    assert "빌드확인" in tr.injected[1]


def test_slash_only_sets_pending(tmp_path):
    """/N 단독 → 선택모드 pending (버튼 클릭과 동일). 주입X."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    InjectCommand().handle(Message("42", "/1", {}), ctx)
    assert tr.injected is None
    assert ctx.pending.get("42", (None,))[0] == 1


def test_slash_two_digits_not_matched(tmp_path):
    """/10 → 일반 메시지(두자리 방지). match 거짓."""
    cmd = InjectCommand()
    assert cmd.match(Message("42", "/10 hello", {})) is False


def test_normalize_question_leading_qmark():
    """선두 '?' → '뭐?' 변환. CC 도움말 단축키(?) 회피."""
    from imadhd.commands.inject_command import _normalize_question as nq
    assert nq("?") == "뭐?"
    assert nq("??") == "뭐?"                       # ? 여러 개
    assert nq("?지금뭐야") == "뭐? 지금뭐야"
    assert nq("??여러개") == "뭐? 여러개"
    assert nq("그냥문장") == "그냥문장"             # ? 아니면 그대로
    assert nq("끝에물음?") == "끝에물음?"           # 선두만 변환


def test_do_inject_question_mark_becomes_mwo(tmp_path):
    """텔레그램 '?' 시작 주입 → '뭐?' 변환되어 CC 전달."""
    from imadhd.commands.inject_command import do_inject
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=999, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport(alive=True)
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    do_inject(ctx, 1, "?이거뭐야", "42")
    assert tr.injected is not None
    text = tr.injected[1]
    assert text.startswith("뭐?")
    assert "이거뭐야" in text
    assert "[A.D.H.D]" in text
