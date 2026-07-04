"""/open /close /stop 명령 단위 테스트. 실제 프로세스/윈도우 없이 페이크로 검증."""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.open_command import OpenCommand
from imadhd.commands.close_command import CloseCommand
from imadhd.commands.stop_command import StopCommand


class FakeInfo:
    def __init__(self, number=1, hwnd=111, pid=222):
        self.number = number
        self.hwnd = hwnd
        self.pid = pid

    def to_dict(self):
        return {"hwnd": self.hwnd, "pid": self.pid}


class FakeRegistry:
    def __init__(self, infos=None):
        self._infos = infos or {}
        self.released = []

    def get(self, n):
        return self._infos.get(n)

    def release(self, n):
        self.released.append(n)
        return True


class FakeResult:
    def __init__(self, delivered=True):
        self.delivered = delivered


class FakeTransport:
    def __init__(self, alive=True):
        self.alive = alive
        self.sent_keys = []

    def is_alive(self, target):
        return self.alive

    def send_key(self, target, vk):
        self.sent_keys.append((target, vk))
        return FakeResult()


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def _ctx(reg=None, transport=None, tg=None):
    return CommandContext(
        settings=None,
        registry=reg or FakeRegistry(),
        transport=transport or FakeTransport(),
        telegram=tg or FakeTelegram(),
    )


# ---------- match() ----------

def test_open_matches_triggers():
    c = OpenCommand()
    assert c.match(Message("1", "/open", {}))
    assert c.match(Message("1", "/새터미널", {}))
    # 숫자 인자(슬롯 선택 등과 충돌 방지)만 제외. 모델명/glm 인자는 test_open_command_provider.py 참조.
    assert not c.match(Message("1", "/open 1", {}))


def test_close_matches_with_and_without_arg():
    c = CloseCommand()
    assert c.match(Message("1", "/close 1", {}))
    assert c.match(Message("1", "/close", {}))          # 사용법 안내 경로도 매칭
    assert not c.match(Message("1", "check logs", {}))


def test_stop_matches_with_and_without_arg():
    c = StopCommand()
    assert c.match(Message("1", "/stop 3", {}))
    assert c.match(Message("1", "/정지", {}))
    assert not c.match(Message("1", "3️⃣ hi", {}))


# ---------- /stop ----------

def test_stop_sends_escape_vk():
    reg = FakeRegistry({1: FakeInfo(1)})
    tr = FakeTransport()
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop 1", {}), _ctx(reg, tr, tg))
    assert tr.sent_keys == [({"hwnd": 111, "pid": 222}, 0x1B)]
    assert "중단" in tg.sent[-1]


def test_stop_missing_slot():
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop 5", {}), _ctx(tg=tg))
    assert "없음" in tg.sent[-1]


def test_stop_no_number_shows_usage():
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop", {}), _ctx(tg=tg))
    assert "사용법" in tg.sent[-1]


def test_stop_dead_terminal_releases_slot():
    reg = FakeRegistry({1: FakeInfo(1)})
    tr = FakeTransport(alive=False)
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop 1", {}), _ctx(reg, tr, tg))
    assert reg.released == [1]
    assert "종료됨" in tg.sent[-1]


# ---------- /close ----------

def test_close_releases_slot_and_notifies():
    reg = FakeRegistry({2: FakeInfo(2, hwnd=0, pid=0)})  # hwnd/pid 0 → WM_CLOSE/taskkill 스킵 경로
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 2", {}), _ctx(reg, tg=tg))
    assert reg.released == [2]
    assert "닫음" in tg.sent[-1]


def test_close_missing_slot():
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 9", {}), _ctx(tg=tg))
    assert "없음" in tg.sent[-1]


def test_close_no_number_shows_usage():
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close", {}), _ctx(tg=tg))
    assert "사용법" in tg.sent[-1]
