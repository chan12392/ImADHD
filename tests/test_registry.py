import json

from imadhd.core.registry import JSONFileRegistry, SessionInfo


def make(path, slots=6):
    return JSONFileRegistry(path, slots)


def test_claim_assigns_lowest(tmp_path):
    reg = make(tmp_path / "r.json")
    n = reg.claim_slot("s1", hwnd=100, pid=1, cwd="c", started_at="t")
    assert n == 1


def test_claim_assigns_next(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("s1", 100, 1, "c", "t")
    n = reg.claim_slot("s2", 200, 2, "c", "t")
    assert n == 2


def test_claim_reuses_session_id(tmp_path):
    reg = make(tmp_path / "r.json")
    n1 = reg.claim_slot("s1", 100, 1, "c", "t1")
    n2 = reg.claim_slot("s1", 300, 9, "c2", "t2")
    assert n1 == n2 == 1
    info = reg.get(1)
    assert info.pid == 9 and info.cwd == "c2"


def test_claim_fills_gap(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("s1", 1, 1, "c", "t")
    reg.claim_slot("s2", 2, 2, "c", "t")
    reg.release(1)
    n = reg.claim_slot("s3", 3, 3, "c", "t")
    assert n == 1


def test_claim_returns_none_when_full(tmp_path):
    reg = make(tmp_path / "r.json", slots=2)
    reg.claim_slot("s1", 1, 1, "c", "t")
    reg.claim_slot("s2", 2, 2, "c", "t")
    assert reg.claim_slot("s3", 3, 3, "c", "t") is None


def test_release_and_get(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("s1", 1, 1, "c", "t")
    assert reg.get(1) is not None
    assert reg.release(1) is True
    assert reg.get(1) is None


def test_find_by_session(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("s1", 1, 1, "c", "t")
    reg.claim_slot("s2", 2, 2, "c", "t")
    info = reg.find_by_session("s2")
    assert info is not None and info.number == 2


def test_active_sorted(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("b", 2, 2, "c", "t")
    reg.claim_slot("a", 1, 1, "c", "t")
    nums = [s.number for s in reg.active()]
    assert nums == [1, 2]


def test_atomic_write_leaves_valid_json(tmp_path):
    reg = make(tmp_path / "r.json")
    reg.claim_slot("s1", 1, 1, "c", "t")
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert "1" in data and data["1"]["session_id"] == "s1"
