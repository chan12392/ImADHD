"""claim_slot pid 재사용 테스트 — /resume 중복 슬롯 방지."""
from imadhd.core.registry import JSONFileRegistry


def _reg(tmp_path):
    return JSONFileRegistry(tmp_path / "r.json", max_slots=6)


def test_same_pid_reuses_slot(tmp_path):
    """같은 pid(같은 CC), 다른 session_id(/resume) → 같은 슬롯 재사용."""
    reg = _reg(tmp_path)
    n1 = reg.claim_slot("sess-A", hwnd=1, pid=999, cwd="c", started_at="t")
    n2 = reg.claim_slot("sess-B", hwnd=1, pid=999, cwd="c", started_at="t")
    assert n1 == n2                              # 같은 슬롯
    assert reg.get(n1).session_id == "sess-B"    # 세션 갱신
    assert len(reg.active()) == 1                # 중복 없음


def test_different_pid_new_slot(tmp_path):
    """다른 pid(다른 CC) → 새 슬롯."""
    reg = _reg(tmp_path)
    n1 = reg.claim_slot("sess-A", hwnd=1, pid=999, cwd="c", started_at="t")
    n2 = reg.claim_slot("sess-B", hwnd=2, pid=888, cwd="c", started_at="t")
    assert n1 != n2
    assert len(reg.active()) == 2


def test_same_session_still_reuses(tmp_path):
    """동일 session_id 재시작 → 같은 슬롯(기존 동작 유지)."""
    reg = _reg(tmp_path)
    n1 = reg.claim_slot("sess-A", hwnd=1, pid=999, cwd="c", started_at="t")
    n2 = reg.claim_slot("sess-A", hwnd=1, pid=999, cwd="c", started_at="t2")
    assert n1 == n2
