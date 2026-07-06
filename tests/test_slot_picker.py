"""slot_picker 인라인 팝업 테스트 (parse_callback / build_slot_keyboard).

use 팝업 끝 "🔓 고정 해제" 버튼(s:use:off → (use,0)) 검증 포함 (대표님 2026-07-07).
"""
from imadhd.core import slot_picker


# ───────────────────────── parse_callback ─────────────────────────

def test_parse_callback_normal():
    assert slot_picker.parse_callback("s:close:3") == ("close", 3)
    assert slot_picker.parse_callback("s:use:1") == ("use", 1)
    assert slot_picker.parse_callback("s:new:9") == ("new", 9)
    assert slot_picker.parse_callback("s:stop:5") == ("stop", 5)


def test_parse_callback_use_off_returns_zero():
    """s:use:off → (use, 0). use_command 가 /use 0 → 해제 분기 진입."""
    assert slot_picker.parse_callback("s:use:off") == ("use", 0)


def test_parse_callback_off_rejected_for_non_use():
    """close/stop/new + off → None. 해제 버튼은 use 전용."""
    assert slot_picker.parse_callback("s:close:off") is None
    assert slot_picker.parse_callback("s:stop:off") is None
    assert slot_picker.parse_callback("s:new:off") is None


def test_parse_callback_invalid():
    assert slot_picker.parse_callback("s:bogus:1") is None      # 알수없 action
    assert slot_picker.parse_callback("s:close:0") is None      # 0 미허용(num<1)
    assert slot_picker.parse_callback("s:close:-1") is None
    assert slot_picker.parse_callback("s:close:abc") is None    # 비숫자
    assert slot_picker.parse_callback("x:close:1") is None      # 접두 불일치
    assert slot_picker.parse_callback("") is None
    assert slot_picker.parse_callback("s:close") is None        # 파트 부족(2개)
    assert slot_picker.parse_callback("s:close:1:2") is None    # 파트 과잉(4개)


# ───────────────────────── build_slot_keyboard ─────────────────────────

def test_build_keyboard_numbers_and_callbacks():
    kb = slot_picker.build_slot_keyboard([(1, "⭕"), (2, "🎯")], "close")
    flat = [b for row in kb for b in row]
    assert len(flat) == 2
    assert all(b["callback_data"].startswith("s:close:") for b in flat)
    assert flat[0]["callback_data"] == "s:close:1"
    assert flat[1]["callback_data"] == "s:close:2"


def test_build_keyboard_use_has_unpin_button():
    """use 팝업 마지막 행 = 🔓 고정 해제 (s:use:off). 단독 행."""
    kb = slot_picker.build_slot_keyboard([(1, "⭕"), (2, "📝")], "use")
    last_row = kb[-1]
    assert len(last_row) == 1                      # 단독 행
    btn = last_row[0]
    assert btn["callback_data"] == "s:use:off"
    assert "해제" in btn["text"]


def test_build_keyboard_non_use_no_unpin():
    """close/stop/new 팝업엔 해제 버튼 없음."""
    for action in ("close", "stop", "new"):
        kb = slot_picker.build_slot_keyboard([(1, "⭕")], action)
        flat = [b for row in kb for b in row]
        assert all("off" not in b["callback_data"] for b in flat), action


def test_build_keyboard_cols_max_three():
    """COLS=3 — 번호 행은 행당 ≤3 (해제 단독행 제외)."""
    nums = [(n, "⭕") for n in range(1, 7)]         # 6슬롯
    kb = slot_picker.build_slot_keyboard(nums, "close")
    for row in kb:
        assert len(row) <= slot_picker.COLS
