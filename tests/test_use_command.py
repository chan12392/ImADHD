"""/use 고정 타겟 명령 + sticky 영속 테스트.

/use N → ctx.sticky[chat]=N + sticky.json 저장 + 🎯 안내
/use off → 해제 + 파일 반영
슬롯 없음/종료 → 거부
"""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.use_command import UseCommand
from imadhd.core import sticky as sticky_store


class FakeInfo:
    def __init__(self, number=1):
        self.number = number
        self.hwnd = 1
        self.pid = 1

    def to_dict(self):
        return {"hwnd": self.hwnd, "pid": self.pid}


class FakeRegistry:
    def __init__(self, alive_nums):
        self._infos = {n: FakeInfo(n) for n in alive_nums}
        self.released = []

    def get(self, n):
        return self._infos.get(n)

    def release(self, n):
        self.released.append(n)


class FakeTransport:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self, target):
        return self.alive


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


class FakeSettings:
    def __init__(self, data_dir, max_slots=6):
        self.data_dir = data_dir
        self.max_slots = max_slots


def _ctx(tmp_path, alive_nums=(1,), transport_alive=True, sticky=None):
    ctx = CommandContext(
        settings=FakeSettings(tmp_path),
        registry=FakeRegistry(alive_nums),
        transport=FakeTransport(transport_alive),
        telegram=FakeTelegram(),
    )
    ctx.sticky = sticky or {}
    return ctx


# ---------- match() ----------

def test_match_use_and_korean_triggers():
    c = UseCommand()
    assert c.match(Message("1", "/use 3", {}))
    assert c.match(Message("1", "/use off", {}))
    assert c.match(Message("1", "/고정 2", {}))
    assert c.match(Message("1", "/타겟 off", {}))
    assert not c.match(Message("1", "/uselog", {}))   # 접두 아님
    assert not c.match(Message("1", "hello", {}))


# ---------- /use N 설정 ----------

def test_use_sets_sticky_and_persists(tmp_path):
    ctx = _ctx(tmp_path, alive_nums=(3,))
    cmd = UseCommand()
    cmd.handle(Message("1", "/use 3", {}), ctx)
    assert ctx.sticky == {"1": 3}
    # 영속 파일 반영
    assert sticky_store.load(ctx.settings.data_dir) == {"1": 3}
    # 🎯 안내 송신
    assert any("🎯" in t and "3" in t for t in ctx.telegram.sent)


def test_use_rejects_dead_slot(tmp_path):
    ctx = _ctx(tmp_path, alive_nums=(1,), transport_alive=False)
    cmd = UseCommand()
    cmd.handle(Message("1", "/use 1", {}), ctx)
    assert ctx.sticky == {}                          # 설정 안 됨
    assert any("❌" in t for t in ctx.telegram.sent)


def test_use_rejects_missing_slot(tmp_path):
    ctx = _ctx(tmp_path, alive_nums=(1,))
    cmd = UseCommand()
    cmd.handle(Message("1", "/use 5", {}), ctx)
    assert ctx.sticky == {}
    assert any("❌" in t for t in ctx.telegram.sent)


def test_use_rejects_out_of_range(tmp_path):
    ctx = _ctx(tmp_path, alive_nums=(1,))
    cmd = UseCommand()
    cmd.handle(Message("1", "/use 99", {}), ctx)
    assert ctx.sticky == {}
    assert any("❌" in t for t in ctx.telegram.sent)


def test_use_no_arg_shows_usage(tmp_path):
    ctx = _ctx(tmp_path)
    cmd = UseCommand()
    cmd.handle(Message("1", "/use", {}), ctx)
    assert ctx.sticky == {}
    assert any("사용법" in t for t in ctx.telegram.sent)


# ---------- /use off 해제 ----------

def test_use_off_clears_sticky(tmp_path):
    ctx = _ctx(tmp_path, sticky={"1": 3})
    sticky_store.save(ctx.settings.data_dir, ctx.sticky)
    cmd = UseCommand()
    cmd.handle(Message("1", "/use off", {}), ctx)
    assert ctx.sticky == {}
    assert sticky_store.load(ctx.settings.data_dir) == {}


def test_use_off_korean_synonym(tmp_path):
    ctx = _ctx(tmp_path, sticky={"1": 2})
    cmd = UseCommand()
    cmd.handle(Message("1", "/고정 해제", {}), ctx)
    assert ctx.sticky == {}


# ---------- sticky 영속 ----------

def test_sticky_save_load_roundtrip(tmp_path):
    sticky_store.save(tmp_path, {"chat-a": 1, "chat-b": 5})
    loaded = sticky_store.load(tmp_path)
    assert loaded == {"chat-a": 1, "chat-b": 5}


def test_sticky_load_missing_returns_empty(tmp_path):
    assert sticky_store.load(tmp_path / "nope") == {}


def test_sticky_load_corrupt_returns_empty(tmp_path):
    (tmp_path / "sticky.json").write_text("{not json", encoding="utf-8")
    assert sticky_store.load(tmp_path) == {}


def test_sticky_load_coerces_int(tmp_path):
    """파일에 str 값이 섞여도 int 로 정규화."""
    (tmp_path / "sticky.json").write_text('{"c": "4"}', encoding="utf-8")
    assert sticky_store.load(tmp_path) == {"c": 4}
