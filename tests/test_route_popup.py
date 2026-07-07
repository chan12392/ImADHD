"""번호 없는 본문 라우팅 팝업 — _route_keyboard 단위 테스트 (2026-07-07).

router.run() 은 롱폴 루프라 _handle_callback/팝업 송신은 closure 로 직접
단위테스트 불가. 순수함수 _route_keyboard(callback_data 스키마·3열 배치·이모지
매핑) 만 검증. 송신·콜백 주입 로직은 router 본문 리뷰로 확인.
"""
from imadhd.core.router import _route_keyboard


def test_keyboard_callback_data_scheme():
    kb = _route_keyboard([1, 2, 3])
    flat = [b for row in kb for b in row]
    assert [b["callback_data"] for b in flat] == ["r:1", "r:2", "r:3"]


def test_keyboard_emoji_labels():
    kb = _route_keyboard([1, 2])
    flat = [b for row in kb for b in row]
    assert flat[0]["text"] == "1️⃣ 1번"
    assert flat[1]["text"] == "2️⃣ 2번"


def test_keyboard_three_column_chunking():
    kb = _route_keyboard([1, 2, 3, 4, 5])
    # 3열 → [1,2,3] / [4,5]
    assert len(kb) == 2
    assert [b["callback_data"] for b in kb[0]] == ["r:1", "r:2", "r:3"]
    assert [b["callback_data"] for b in kb[1]] == ["r:4", "r:5"]


def test_keyboard_single_slot():
    kb = _route_keyboard([7])
    assert kb == [[{"text": "7️⃣ 7번", "callback_data": "r:7"}]]


def test_keyboard_empty():
    assert _route_keyboard([]) == []


def test_keyboard_high_number_fallback_label():
    """10번 같이 이모지 매핑 없으면 숫자 그대로 라벨(콜백은 정상)."""
    kb = _route_keyboard([10])
    b = kb[0][0]
    assert b["callback_data"] == "r:10"
    assert "10번" in b["text"]
