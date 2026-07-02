"""PinBoard(ReplyKeyboard) 상태 텍스트 + 갱신 로직 테스트."""
from imadhd.boards.pin_board import PinBoard, NUM_EMOJI
from imadhd.core.registry import JSONFileRegistry


class FakeTG:
    def __init__(self):
        self.sent = []              # (chat, text, markup)
        self.edited_markup = []     # (chat, mid, markup)
        self._next_mid = 100
    def send(self, chat_id, text, reply_markup=None):
        mid = self._next_mid
        self._next_mid += 1
        self.sent.append((chat_id, text, reply_markup))
        return mid
    def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.edited_markup.append((chat_id, message_id, reply_markup))


def _board(tmp_path, reg=None):
    reg = reg or JSONFileRegistry(tmp_path / "r.json", max_slots=6)
    return PinBoard(FakeTG(), reg, "chat1", tmp_path, max_slots=6), reg


def test_status_all_dead_when_empty(tmp_path):
    board, _ = _board(tmp_path)
    assert "❌" in board.status_text()
    assert board.status_text().count("❌") == 6


def test_status_idle_is_check_busy_is_memo(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")   # 1번 idle
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")   # 2번
    reg.set_status(2, "busy")
    text = board.status_text()
    assert f"{NUM_EMOJI[1]}⭕" in text
    assert f"{NUM_EMOJI[2]}📝" in text
    assert f"{NUM_EMOJI[3]}❌" in text


def test_create_sends_reply_keyboard(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    assert len(board.tg.sent) == 1
    assert board.msg_id is not None
    chat, text, markup = board.tg.sent[0]
    assert markup is not None
    assert "keyboard" in markup           # ReplyKeyboard (inline 아님)
    assert "inline_keyboard" not in markup


def test_refresh_skips_when_unchanged(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    board.refresh_if_changed()            # 변화 없음
    assert board.tg.edited_markup == []


def test_refresh_edits_markup_on_status_change(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    reg.set_status(1, "busy")             # idle→busy
    board.refresh_if_changed()
    assert len(board.tg.edited_markup) == 1
    _chat, _mid, markup = board.tg.edited_markup[0]
    assert "📝" in markup["keyboard"][0][0]["text"]


def test_markup_is_reply_keyboard_grid(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")   # 1번 idle
    markup = board.status_markup()
    assert markup["resize_keyboard"] is True
    kb = markup["keyboard"]
    # 6슬롯 / 3열 = 2행
    assert len(kb) == 2
    assert len(kb[0]) == 3
    btn1 = kb[0][0]
    assert "callback_data" not in btn1            # ReplyKeyboard: callback 없음
    assert f"{NUM_EMOJI[1]}⭕" == btn1["text"]     # 1번 idle
    assert f"{NUM_EMOJI[2]}❌" == kb[0][1]["text"]  # 2번 빈슬롯
