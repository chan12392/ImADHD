"""registry.sweep_dead 테스트. liveness 함수 주입으로 단위테스트."""
import json
from imadhd.core.registry import JSONFileRegistry, SessionInfo


def _make(tmp_path):
    p = tmp_path / "reg.json"
    return JSONFileRegistry(str(p), max_slots=6)


def test_sweep_removes_only_dead(tmp_path):
    reg = _make(tmp_path)
    reg.claim_slot("alive-session", hwnd=100, pid=1, cwd="x", started_at="t")
    reg.claim_slot("dead-session", hwnd=200, pid=2, cwd="x", started_at="t")
    alive_hwnds = {100}
    removed = reg.sweep_dead(lambda info: info.hwnd in alive_hwnds)
    assert removed == 1
    assert reg.find_by_session("alive-session") is not None
    assert reg.find_by_session("dead-session") is None


def test_sweep_keeps_all_when_alive(tmp_path):
    reg = _make(tmp_path)
    reg.claim_slot("a", hwnd=1, pid=1, cwd="x", started_at="t")
    reg.claim_slot("b", hwnd=2, pid=2, cwd="x", started_at="t")
    removed = reg.sweep_dead(lambda info: True)
    assert removed == 0
    assert len(reg.active()) == 2


def test_sweep_empty_registry(tmp_path):
    reg = _make(tmp_path)
    removed = reg.sweep_dead(lambda info: False)
    assert removed == 0
    assert reg.active() == []


def test_sweep_all_dead_clears_then_reuses_slot1(tmp_path):
    reg = _make(tmp_path)
    reg.claim_slot("dead1", hwnd=1, pid=1, cwd="x", started_at="t")
    reg.claim_slot("dead2", hwnd=2, pid=2, cwd="x", started_at="t")
    reg.sweep_dead(lambda info: False)
    # 정리 후 신규 세션 → 가장 낮은 빈 슬롯(1번) 재할당
    num = reg.claim_slot("fresh", hwnd=9, pid=9, cwd="x", started_at="t")
    assert num == 1
