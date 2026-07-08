"""busy_hook 단위 테스트.

1) _heal_session_drift: /clear 직후 session_id 드리프트 자가치유. 같은 cwd 슬롯의
   session_id 를 new 로 갱신(claim_slot) + marker_pending/<old> → /<new> 복사.
2) _prompt_has_marker: UserPromptSubmit prompt 의 reply_marker 유무 → 출처 판별.
   마커 있으면 텔레그램 인입(busy), 없으면 데스크톱 직접(busy 안 됨).
"""
from pathlib import Path

from imadhd.hooks.busy_hook import _heal_session_drift, _prompt_has_marker


class _Slot:
    def __init__(self, number, session_id, cwd, hwnd=100, pid=999, started_at="2026-01-01T00:00:00"):
        self.number = number
        self.session_id = session_id
        self.cwd = cwd
        self.hwnd = hwnd
        self.pid = pid
        self.started_at = started_at
        self.tmux_pane = ""


class _FakeReg:
    def __init__(self, slots):
        self._slots = slots
        self.claimed = None

    def active(self):
        return list(self._slots)

    def claim_slot(self, session_id, hwnd, pid, cwd, started_at, tmux_pane=""):
        self.claimed = dict(session_id=session_id, hwnd=hwnd, pid=pid,
                            cwd=cwd, started_at=started_at, tmux_pane=tmux_pane)
        # 시뮬: 매칭 슬롯 session_id 갱신
        for s in self._slots:
            if s.pid == pid:
                s.session_id = session_id
        return self._slots[0].number if self._slots else None


def test_heal_updates_session_id_and_copies_marker(tmp_path):
    data_dir = tmp_path / ".imadhd"
    mp = data_dir / "marker_pending"
    mp.mkdir(parents=True)
    (mp / "OLD-1111").write_text("123.0", encoding="utf-8")

    reg = _FakeReg([_Slot(1, "OLD-1111", "C:/proj")])
    ok = _heal_session_drift(reg, str(data_dir), "NEW-2222", "C:/proj")
    assert ok is True
    # claim_slot 이 new sid 로 호출
    assert reg.claimed["session_id"] == "NEW-2222"
    assert reg.claimed["pid"] == 999
    # marker 이전
    assert (mp / "NEW-2222").exists()
    assert (mp / "NEW-2222").read_text(encoding="utf-8") == "123.0"


def test_heal_no_matching_cwd_returns_false(tmp_path):
    reg = _FakeReg([_Slot(1, "OLD-1111", "C:/other")])
    ok = _heal_session_drift(reg, str(tmp_path), "NEW-2222", "C:/proj")
    assert ok is False
    assert reg.claimed is None


def test_heal_no_drift_same_session_returns_false(tmp_path):
    """session_id 이미 일치 → 치유 불필요."""
    reg = _FakeReg([_Slot(1, "SAME-3333", "C:/proj")])
    ok = _heal_session_drift(reg, str(tmp_path), "SAME-3333", "C:/proj")
    assert ok is False
    assert reg.claimed is None


def test_heal_missing_cwd_returns_false(tmp_path):
    """cwd 없으면 매칭 불가 → 치유 안 함."""
    reg = _FakeReg([_Slot(1, "OLD-1111", "C:/proj")])
    assert _heal_session_drift(reg, str(tmp_path), "NEW-2222", "") is False


def test_heal_marker_absent_still_claims(tmp_path):
    """old marker 없어도 session_id 갱신은 수행(직전 inject 없던 턴)."""
    data_dir = tmp_path / ".imadhd"
    (data_dir / "marker_pending").mkdir(parents=True)
    reg = _FakeReg([_Slot(1, "OLD-1111", "C:/proj")])
    ok = _heal_session_drift(reg, str(data_dir), "NEW-2222", "C:/proj")
    assert ok is True
    assert reg.claimed["session_id"] == "NEW-2222"


# ---------- _prompt_has_marker (출처 게이트 2026-07-09) ----------

MARKER = "[A.D.H.D]"


def test_prompt_has_marker_true_for_tg_inject():
    """텔레그램 주입(inject_command가 마커 부착) → busy."""
    assert _prompt_has_marker(f"작업해줘 {MARKER}", MARKER) is True


def test_prompt_has_marker_false_for_desktop_direct():
    """데스크톱 앱/터미널 직접 타이핑(마커 없음) → busy 안 됨."""
    assert _prompt_has_marker("그냥 직접 친 질문", MARKER) is False


def test_prompt_has_marker_false_for_empty():
    assert _prompt_has_marker("", MARKER) is False
    assert _prompt_has_marker(None, MARKER) is False  # type: ignore[arg-type]
