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

    def active(self):
        return list(self._infos.values())


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


def test_stop_no_number_no_active_informs():
    """인자 없음 + 활성 0 → slot_picker 가 '열린 터미널 없음' 안내."""
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop", {}), _ctx(tg=tg))
    assert "열린" in tg.sent[-1]


def test_stop_dead_terminal_releases_slot():
    reg = FakeRegistry({1: FakeInfo(1)})
    tr = FakeTransport(alive=False)
    tg = FakeTelegram()
    StopCommand().handle(Message("1", "/stop 1", {}), _ctx(reg, tr, tg))
    assert reg.released == [1]
    assert "종료됨" in tg.sent[-1]


# ---------- /close ----------

def test_close_releases_slot_and_notifies():
    """/close = 슬롯 해제만, 터미널 종료X (대표님 2026-07-07 지시)."""
    reg = FakeRegistry({2: FakeInfo(2, hwnd=0, pid=0)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 2", {}), _ctx(reg, tg=tg))
    assert reg.released == [2]
    assert "해제" in tg.sent[-1]


def test_close_missing_slot():
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 9", {}), _ctx(tg=tg))
    assert "없음" in tg.sent[-1]


def test_close_no_number_no_active_informs():
    """인자 없음 + 활성 0 → slot_picker 가 '열린 터미널 없음' 안내."""
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close", {}), _ctx(tg=tg))
    assert "열린" in tg.sent[-1]


# ---------- find_tab_root (WT 탭 루트 역추적, 2026-07-07) ----------

def test_find_tab_root_returns_wt_direct_child(monkeypatch):
    """CC 부모체인에서 WT 직전 자식(탭 루트=cmd.exe) pid 반환."""
    from imadhd.core import proc_win
    fake = {
        400: ("claude.exe", 300),
        300: ("python.exe", 200),    # host.py
        200: ("cmd.exe", 100),       # WT 직전 자식 = 탭 루트
        100: ("windowsterminal.exe", 50),
    }
    monkeypatch.setattr(proc_win, "snapshot", lambda: fake)
    assert proc_win.find_tab_root(400) == 200


def test_find_tab_root_cc_is_direct_wt_child(monkeypatch):
    """CC 가 WT 직접 자식(host.py 없는 환경) → CC 자체가 탭 루트."""
    from imadhd.core import proc_win
    fake = {400: ("claude.exe", 100), 100: ("windowsterminal.exe", 50)}
    monkeypatch.setattr(proc_win, "snapshot", lambda: fake)
    assert proc_win.find_tab_root(400) == 400


def test_find_tab_root_no_wt_returns_none(monkeypatch):
    """WT 를 못 찾으면(비WT/tmux/직접실행) None → 호출측 폴백(엉뚱 kill 방지)."""
    from imadhd.core import proc_win
    fake = {400: ("claude.exe", 300), 300: ("python.exe", 0)}
    monkeypatch.setattr(proc_win, "snapshot", lambda: fake)
    assert proc_win.find_tab_root(400) is None


def test_find_tab_root_zero_pid_safe():
    """pid=0 → 즉시 None(방어)."""
    from imadhd.core import proc_win
    assert proc_win.find_tab_root(0) is None


def test_find_tab_root_cycle_safe(monkeypatch):
    """부모체인에 루프(비정상) → seen 셋으로 무한루프 회피, None."""
    from imadhd.core import proc_win
    fake = {400: ("a.exe", 300), 300: ("b.exe", 400)}   # 루프, WT 없음
    monkeypatch.setattr(proc_win, "snapshot", lambda: fake)
    assert proc_win.find_tab_root(400) is None


# ---------- /close tab_root 우선 kill ----------

def test_close_kills_tab_root_when_found(monkeypatch):
    """find_tab_root 발견 → terminate_tree(tab_root). host_pid/pid 보다 우선."""
    import imadhd.commands.close_command as cc
    monkeypatch.setattr(cc, "find_tab_root", lambda pid: 9999)
    killed = []
    monkeypatch.setattr(cc, "terminate_tree", lambda pid: killed.append(pid) or True)
    reg = FakeRegistry({1: FakeInfo(1, pid=222, hwnd=111)})
    tg = FakeTelegram()
    cc.CloseCommand().handle(Message("1", "/close 1", {}), _ctx(reg, tg=tg))
    assert killed == [9999]
    assert reg.released == [1]


def test_close_falls_back_to_pid_when_no_tab_root(monkeypatch):
    """find_tab_root None → host_pid(없음) → info.pid 폴백."""
    import imadhd.commands.close_command as cc
    monkeypatch.setattr(cc, "find_tab_root", lambda pid: None)
    killed = []
    monkeypatch.setattr(cc, "terminate_tree", lambda pid: killed.append(pid) or True)
    reg = FakeRegistry({1: FakeInfo(1, pid=222, hwnd=111)})
    cc.CloseCommand().handle(Message("1", "/close 1", {}), _ctx(reg, tg=FakeTelegram()))
    assert killed == [222]
