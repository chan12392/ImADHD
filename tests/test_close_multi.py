"""/close 다중·all 확장 단위 테스트 (2026-07-07).

  /close N M ...   공백 다중
  /close N,M,...   콤마 다중 (띄어쓰기 혼합 OK)
  /close all       활성 전체
페이크 registry/transport + terminate_tree monkeypatch 로 kill 성공 경로 검증.
"""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.close_command import CloseCommand


class FakeInfo:
    def __init__(self, number, pid, hwnd=0):
        self.number = number
        self.pid = pid
        self.hwnd = hwnd

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
        return sorted(self._infos.values(), key=lambda i: i.number)


class FakeTransport:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self, target):
        return self.alive

    def send_key(self, target, vk):
        return None


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def _ctx(reg, tg, transport=None):
    return CommandContext(
        settings=None,
        registry=reg,
        transport=transport or FakeTransport(),
        telegram=tg,
    )


def _patch_kill(monkeypatch, killed=True):
    """terminate_tree 항상 killed 결과, find_tab_root None(→pid 폴백)."""
    import imadhd.commands.close_command as cc
    monkeypatch.setattr(cc, "find_tab_root", lambda pid: None)
    monkeypatch.setattr(cc, "terminate_tree", lambda pid: killed)


# ---------- 인자 파싱 ----------

def test_parse_single():
    assert CloseCommand._parse_targets(["1"]) == (False, [1])


def test_parse_space_multi_dedup():
    is_all, nums = CloseCommand._parse_targets(["1", "2", "1"])
    assert is_all is False
    assert nums == [1, 2]   # 중복 제거·순서 보존


def test_parse_comma_multi():
    assert CloseCommand._parse_targets(["1,2,3"]) == (False, [1, 2, 3])


def test_parse_comma_space_mix():
    assert CloseCommand._parse_targets(["1,", "2,", "3"]) == (False, [1, 2, 3])


def test_parse_all_keyword():
    assert CloseCommand._parse_targets(["all"]) == (True, [])
    # "all" 이 섞이면 all 우선
    assert CloseCommand._parse_targets(["all", "1"]) == (True, [])


def test_parse_invalid_returns_none():
    assert CloseCommand._parse_targets(["abc"]) == (False, None)
    assert CloseCommand._parse_targets(["1", "x"]) == (False, None)
    assert CloseCommand._parse_targets(["0"]) == (False, None)   # 0번 불가


# ---------- /close all ----------

def test_close_all_kills_every_active(monkeypatch):
    _patch_kill(monkeypatch, killed=True)
    reg = FakeRegistry({1: FakeInfo(1, 101), 2: FakeInfo(2, 202), 3: FakeInfo(3, 303)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close all", {}), _ctx(reg, tg))
    assert sorted(reg.released) == [1, 2, 3]
    assert any("종료: 1, 2, 3번" in t for t in tg.sent)


def test_close_all_no_active_informs(monkeypatch):
    _patch_kill(monkeypatch)
    reg = FakeRegistry({})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close all", {}), _ctx(reg, tg))
    assert "열린" in tg.sent[-1]
    assert reg.released == []


# ---------- 공백/콤마 다중 ----------

def test_close_space_multi_summary(monkeypatch):
    _patch_kill(monkeypatch, killed=True)
    reg = FakeRegistry({1: FakeInfo(1, 101), 2: FakeInfo(2, 202)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 1 2", {}), _ctx(reg, tg))
    assert sorted(reg.released) == [1, 2]
    assert any("종료: 1, 2번" in t for t in tg.sent)


def test_close_comma_multi_summary(monkeypatch):
    _patch_kill(monkeypatch, killed=True)
    reg = FakeRegistry({1: FakeInfo(1, 101), 2: FakeInfo(2, 202)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 1,2", {}), _ctx(reg, tg))
    assert sorted(reg.released) == [1, 2]


def test_close_multi_skips_missing_and_reports(monkeypatch):
    """활성 1,3 + 9번 없음 → 1,3 종료, 9번 '없음' 요약."""
    _patch_kill(monkeypatch, killed=True)
    reg = FakeRegistry({1: FakeInfo(1, 101), 3: FakeInfo(3, 303)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 1,3,9", {}), _ctx(reg, tg))
    assert sorted(reg.released) == [1, 3]   # 9번은 release X
    joined = " ".join(tg.sent)
    assert "종료: 1, 3번" in joined
    assert "없음: 9번" in joined


def test_close_multi_fail_path_reports(monkeypatch):
    """terminate_tree 실패 → '종료 실패(슬롯은 해제)' 요약."""
    _patch_kill(monkeypatch, killed=False)
    reg = FakeRegistry({1: FakeInfo(1, 101)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 1 1", {}), _ctx(reg, tg))   # 중복 1→1
    assert reg.released == [1]
    assert any("종료 실패" in t and "해제" in t for t in tg.sent)


# ---------- 사용법 ----------

def test_close_invalid_arg_shows_usage(monkeypatch):
    _patch_kill(monkeypatch)
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close abc", {}), _ctx(FakeRegistry({}), tg))
    assert any("사용법" in t for t in tg.sent)


# ---------- 단일 회귀 (새 _close_single 경로) ----------

def test_close_single_still_works(monkeypatch):
    _patch_kill(monkeypatch, killed=True)
    reg = FakeRegistry({2: FakeInfo(2, 202)})
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 2", {}), _ctx(reg, tg))
    assert reg.released == [2]
    assert any("🔒 2번" in t for t in tg.sent)


def test_close_single_missing(monkeypatch):
    _patch_kill(monkeypatch)
    tg = FakeTelegram()
    CloseCommand().handle(Message("1", "/close 9", {}), _ctx(FakeRegistry({}), tg))
    assert any("9번 터미널 없음" in t for t in tg.sent)
