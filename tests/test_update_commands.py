"""/update-adhd 명령 단위 테스트.

2단계 로직(대표님 2026-07-07):
  handle(): fetch → behind 판정 → behind=0 "최신" / behind>0 인라인 yes/no 팝업.
  run_update(): pull → pytest → 분리 restart (콜백 yes 경로).

subprocess·CHANGELOG 접근 monkeypatch 로 검증.
"""
from subprocess import CompletedProcess

from imadhd.commands.base import Message, CommandContext
from imadhd.commands.update_adhd_command import UpdateAdhdCommand, run_update


class FakeTG:
    def __init__(self):
        self.sent = []          # (chat, text, markup)

    def send(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text, reply_markup))


class FakeSettings:
    reply_marker = "[A.D.H.D]"
    data_dir = None


def _cp(returncode=0, stdout="", stderr=""):
    return CompletedProcess(args="", returncode=returncode,
                            stdout=stdout, stderr=stderr)


# ───────────────────────── match ─────────────────────────

def test_update_adhd_match_variants():
    c = UpdateAdhdCommand()
    for t in ["/update-adhd", "/update_adhd", "/UPDATE-ADHD", "  /update-adhd  ",
              "/업데이트-adhd", "update-adhd"]:   # bare 영문도 매칭 (버튼 라벨 슬래시 없음)
        assert c.match(Message("1", t, {})) is True, t
    for t in ["/help", "/update-adhd2"]:
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


def _ctx(tg):
    return CommandContext(settings=FakeSettings(), registry=None,
                          transport=None, telegram=tg)


# ───────────────────────── handle(): behind 판정 + 팝업 ─────────────────────────

def test_handle_already_latest_no_popup(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t0", ""),       # ahead=0 behind=0
    }, popen)
    tg = FakeTG()
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), _ctx(tg))
    assert any("이미 최신" in t for _, t, _ in tg.sent)
    assert all(mk is None for _, _, mk in tg.sent)   # 팝업 송신 없음
    assert popen == []


def test_handle_behind_shows_yesno_popup(monkeypatch):
    """behind>0 → 버전+체인지로그+yes/no 인라인 팝업. run_update 미호출(탭 대기)."""
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "0\t2", ""),       # behind=2
        "show": _cp(0, "## 0.9.9 — 2026-07-10\n- 새기능 X\n- 버그 수정 Y\n", ""),
    }, popen)
    tg = FakeTG()
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), _ctx(tg))
    last_chat, last_text, mk = tg.sent[-1]
    assert mk is not None
    ik = mk["inline_keyboard"]
    callbacks = [b["callback_data"] for row in ik for b in row]
    assert "u:update:yes" in callbacks
    assert "u:update:no" in callbacks
    assert "0.9.9" in last_text                # remote 버전 표시
    assert "behind=2" in last_text
    assert "새기능 X" in last_text or "새기능" in last_text   # 체인지로그 발췌
    assert popen == []                         # 아직 갱신 안 함


def test_handle_fetch_fail(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(1, "", "network err"),
    }, popen)
    tg = FakeTG()
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), _ctx(tg))
    assert any("fetch 실패" in t for _, t, _ in tg.sent)
    assert popen == []


def test_handle_revlist_parse_fail(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "fetch": _cp(0, "", ""),
        "rev-list": _cp(0, "garbage", ""),
    }, popen)
    tg = FakeTG()
    UpdateAdhdCommand().handle(Message("9", "/update-adhd", {}), _ctx(tg))
    assert any("파싱 실패" in t for _, t, _ in tg.sent)


# ───────────────────────── run_update(): 콜백 yes 경로 ─────────────────────────

def test_run_update_success_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "pull": _cp(0, "Updating", ""),
        "pytest": _cp(0, "270 passed", ""),
    }, popen)
    tg = FakeTG()
    run_update(tg, "9")
    assert any("restart" in t for _, t, _ in tg.sent)
    assert len(popen) == 1                      # 분리 지연 restart 1회


def test_run_update_pull_fail_no_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "pull": _cp(1, "", "merge conflict"),
    }, popen)
    tg = FakeTG()
    run_update(tg, "9")
    assert any("pull 실패" in t for _, t, _ in tg.sent)
    assert popen == []


def test_run_update_pytest_fail_no_restart(monkeypatch):
    popen = []
    _patch_subproc(monkeypatch, {
        "pull": _cp(0, "Updating", ""),
        "pytest": _cp(1, "2 failed, 3 passed", ""),
    }, popen)
    tg = FakeTG()
    run_update(tg, "9")
    assert any("pytest 실패" in t for _, t, _ in tg.sent)
    assert popen == []
