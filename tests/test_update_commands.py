"""/update-adhd, /update 명령 단위 테스트.

F1(update_adhd): subprocess 를 monkeypatch 해 git/pytest/popen 흐름 검증.
  - behind=0 → "이미 최신", restart(popen) 미호출.
  - pull 실패 → restart 미호출.
  - pytest 실패 → restart 미호출.
  - 전부 성공 → restart(popen) 1회.
F2(update_cc): do_inject 재사용 + slot 해석(pending/sticky/active단일/0/2+).
"""
from subprocess import CompletedProcess

from imadhd.commands.base import Message, CommandContext
from imadhd.commands.update_adhd_command import UpdateAdhdCommand
from imadhd.commands.update_cc_command import UpdateCcCommand
from imadhd.core.registry import JSONFileRegistry


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeTransport:
    def __init__(self, alive=True):
        self._alive = alive
        self.injected = None

    def is_alive(self, target):
        return self._alive

    def inject(self, target, text, background=False):
        self.injected = (target, text)


class FakeSettings:
    reply_marker = "[A.D.H.D]"
    data_dir = None


def _cp(returncode=0, stdout="", stderr=""):
    return CompletedProcess(args="", returncode=returncode,
                            stdout=stdout, stderr=stderr)


# ───────────────────────── F1: /update-adhd ─────────────────────────

def test_update_adhd_match_variants():
    c = UpdateAdhdCommand()
    for t in ["/update-adhd", "/update_adhd", "/UPDATE-ADHD", "  /update-adhd  ", "/업데이트-adhd"]:
        assert c.match(Message("1", t, {})) is True, t
    for t in ["/update", "/help", "update-adhd", "/update-adhd2"]:
        assert c.match(Message("1", t, {})) is False, t


def _patch_subproc(monkeypatch, script, popen_calls):
    """update_adhd_command.subprocess 의 run/Popen 을 fake 로 교체.
    script = {cmd_부분문자열: CompletedProcess}. 순서대로 첫 매치 반환."""
    mod = "imadhd.commands.update_adhd_command.subprocess"

    def fake_run(cmd, **kw):
        for key, result in script.items():
            if key in cmd:
                return result
        return _cp(0, "", "")

    class _FakePopen:
        def __init__(self, *a, **kw):
            popen_calls.append((a, kw))

    monkeypatch.setattr(mod + ".run", fake_run)
    monkeypatch.setattr(mod + ".Popen", _FakePopen)


def test_update_adhd_already_latest(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t0", ""),  # ahead=0 behind=0
    }, popen)
    tg = FakeTG()
    ctx = CommandContext(settings=FakeSettings(), registry=None, transport=None, telegram=tg)
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), ctx)
    assert any("이미 최신" in t for _, t in tg.sent)
    assert popen == []  # restart 없음


def test_update_adhd_pull_fail_no_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t3", ""),       # behind=3
        "pull": _cp(1, "", "merge conflict"),  # ff-only 실패
    }, popen)
    tg = FakeTG()
    ctx = CommandContext(settings=FakeSettings(), registry=None, transport=None, telegram=tg)
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), ctx)
    assert any("pull 실패" in t for _, t in tg.sent)
    assert popen == []


def test_update_adhd_pytest_fail_no_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t1", ""),
        "pull": _cp(0, "Updating..", ""),
        "pytest": _cp(1, "2 failed, 3 passed", ""),  # pytest 실패
    }, popen)
    tg = FakeTG()
    ctx = CommandContext(settings=FakeSettings(), registry=None, transport=None, telegram=tg)
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), ctx)
    assert any("pytest 실패" in t for _, t in tg.sent)
    assert popen == []


def test_update_adhd_success_triggers_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t2", ""),
        "pull": _cp(0, "Updating..", ""),
        "pytest": _cp(0, "270 passed", ""),
    }, popen)
    tg = FakeTG()
    ctx = CommandContext(settings=FakeSettings(), registry=None, transport=None, telegram=tg)
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), ctx)
    assert any("restart" in t for _, t in tg.sent)
    assert len(popen) == 1  # 분리 지연 restart 1회


# ───────────────────────── F2: /update ─────────────────────────

def test_update_cc_match_variants():
    c = UpdateCcCommand()
    for t in ["/update", "/UPDATE", "  /update  ", "/업데이트"]:
        assert c.match(Message("1", t, {})) is True, t
    for t in ["/update-adhd", "/help", "update", "/1"]:
        assert c.match(Message("1", t, {})) is False, t


def test_update_cc_no_active_terminal(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    tg, tr = FakeTG(), FakeTransport()
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    UpdateCcCommand().handle(Message("9", "/update", {}), ctx)
    assert tr.injected is None
    assert any("열린 CC 없음" in t for _, t in tg.sent)


def test_update_cc_two_active_no_auto(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport()
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    UpdateCcCommand().handle(Message("9", "/update", {}), ctx)
    assert tr.injected is None  # 2개 → 자동 선택 불가
    assert any("번호" in t for _, t in tg.sent)


def test_update_cc_single_active_injects(tmp_path):
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport()
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    UpdateCcCommand().handle(Message("9", "/update", {}), ctx)
    assert tr.injected is not None
    _, text = tr.injected
    assert text == "!claude update"
    assert any("!claude update" in t for _, t in tg.sent)


def test_update_cc_pending_priority(tmp_path):
    """pending > active. pending 슬롯으로 주입."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")  # 1번 active 단일
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")  # 2번 (2개 → active 자동X)
    tg, tr = FakeTG(), FakeTransport()
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    ctx.pending["9"] = (2, 0.0)  # 2번 대기
    UpdateCcCommand().handle(Message("9", "/update", {}), ctx)
    assert tr.injected is not None


def test_update_cc_sticky_priority(tmp_path):
    """sticky > active 단일(active 2개+ 상태서 sticky 사용)."""
    reg = JSONFileRegistry(tmp_path / "r.json")
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")
    tg, tr = FakeTG(), FakeTransport()
    ctx = CommandContext(settings=FakeSettings(), registry=reg, transport=tr, telegram=tg)
    ctx.sticky["9"] = 1
    UpdateCcCommand().handle(Message("9", "/update", {}), ctx)
    assert tr.injected is not None
