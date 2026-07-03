"""ask_manager 단위 테스트 — 인라인 키보드 빌드 / callback 파싱 / 답 수집.
(네트워크·텔레그램 미사용 — 순수 로직만)
"""
from imadhd.core import ask_manager


# ---------- build_inline_keyboard ----------

def test_keyboard_one_button_per_option_and_callback_data():
    opts = [{"label": "A", "description": ""}, {"label": "B", "description": ""}]
    kb = ask_manager.build_inline_keyboard(opts, "abc123def456", 0)
    # 옵션당 한 행
    assert len(kb) == 2
    assert kb[0] == [{"text": "A", "callback_data": "a:abc123def456:0:0"}]
    assert kb[1] == [{"text": "B", "callback_data": "a:abc123def456:0:1"}]


def test_keyboard_empty_label_falls_back():
    kb = ask_manager.build_inline_keyboard([{"label": "", "description": ""}], "id0000000001", 2)
    assert kb == [[{"text": "opt0", "callback_data": "a:id0000000001:2:0"}]]


def test_keyboard_multi_question_uses_item_index():
    # 질문이 여러 개면 item_index 로 구분 — 같은 ask_id 내 충돌 없음.
    kb0 = ask_manager.build_inline_keyboard([{"label": "X"}], "id0000000002", 0)
    kb1 = ask_manager.build_inline_keyboard([{"label": "Y"}], "id0000000002", 1)
    assert kb0[0][0]["callback_data"] == "a:id0000000002:0:0"
    assert kb1[0][0]["callback_data"] == "a:id0000000002:1:0"


# ---------- parse_callback ----------

def test_parse_callback_valid():
    assert ask_manager.parse_callback("a:abc123def456:0:1") == ("abc123def456", 0, 1)
    assert ask_manager.parse_callback("a:id0000000002:3:0") == ("id0000000002", 3, 0)


def test_parse_callback_rejects_garbage():
    assert ask_manager.parse_callback("") is None
    assert ask_manager.parse_callback("hello") is None
    assert ask_manager.parse_callback("b:abc:0:0") is None            # 다른 접두
    assert ask_manager.parse_callback("a:abc:0") is None             # 파트 부족
    assert ask_manager.parse_callback("a:abc:x:0") is None           # 정수 아님
    assert ask_manager.parse_callback("a:abc:0:1:2") is None         # 파트 과잉


# ---------- record_answers / all_answered ----------

def test_all_answered_requires_every_item():
    rec = {"items": [
        {"question": "Q1", "answer": "A"},
        {"question": "Q2", "answer": None},
    ]}
    assert not ask_manager.all_answered(rec)
    rec["items"][1]["answer"] = "B"
    assert ask_manager.all_answered(rec)


def test_all_answered_empty_items_false():
    assert not ask_manager.all_answered({"items": []})


def test_record_answers_skips_unanswered():
    rec = {"items": [
        {"question": "한글질문1", "answer": "첫옵션"},
        {"question": "한글질문2", "answer": None},
    ]}
    out = ask_manager.record_answers(rec)
    assert out == {"한글질문1": "첫옵션"}


# ---------- round-trip write/read ----------

def test_write_load_roundtrip(tmp_path):
    rec = {
        "ask_id": "roundtrip001",
        "session_id": "s1", "chat_id": "123", "slot": 1,
        "items": [{"question": "Q", "header": "h", "options": [{"label": "A"}],
                   "message_id": 5, "answer": "A"}],
        "created_at": "2026-07-03T00:00:00", "status": "answered",
    }
    ask_manager.write_record(tmp_path, rec)
    loaded = ask_manager.load_record(tmp_path, "roundtrip001")
    assert loaded == rec
    assert ask_manager.record_answers(loaded) == {"Q": "A"}


def test_load_missing_returns_none(tmp_path):
    assert ask_manager.load_record(tmp_path, "nope00000000") is None
