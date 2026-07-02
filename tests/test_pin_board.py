"""PinBoard(상단 핀 본문 + ReplyKeyboard 버튼 분리) 테스트."""
from imadhd.boards.pin_board import PinBoard, NUM_EMOJI
from imadhd.core.registry import JSONFileRegistry


class FakeTG:
    def __init__(self):
        self.sent = []          # (chat, text, markup)
        self.edited = []        # (chat, mid, text, markup)
        self.pinned = []        # message_id
        self.deleted = []       # message_id
        self._next_mid = 100
    def send(self, chat_id, text, reply_markup=None, parse_mode=None):
        mid = self._next_mid
        self._next_mid += 1
        self.sent.append((chat_id, text, reply_markup))
        return mid
    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append((chat_id, message_id, text, reply_markup))
    def pin_chat_message(self, chat_id, message_id):
        self.pinned.append(message_id)
    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def _board(tmp_path, reg=None):
    reg = reg or JSONFileRegistry(tmp_path / "r.json", max_slots=6)
    return PinBoard(FakeTG(), reg, "chat1", tmp_path, max_slots=6), reg


def test_status_all_dead_when_empty(tmp_path):
    board, _ = _board(tmp_path)
    assert board.status_text().count("❌") == 6


def test_status_marks(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")   # 1번 idle
    reg.claim_slot("s2", hwnd=2, pid=2, cwd="c", started_at="t")   # 2번
    reg.set_status(2, "busy")
    text = board.status_text()
    assert f"{NUM_EMOJI[1]}.⭕" in text
    assert f"{NUM_EMOJI[2]}.📝" in text
    assert f"{NUM_EMOJI[3]}.❌" in text


def test_create_sends_status_and_keyboard(tmp_path):
    """create → 본문(markup 없음)+핀, 버튼(ReplyKeyboard) 2개 메시지."""
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    assert len(board.tg.sent) == 2                       # status + keyboard
    # status 메시지(markup 없음)
    chat_s, text_s, mk_s = board.tg.sent[0]
    assert mk_s is None
    assert "⭕" in text_s
    assert board.tg.pinned == [board.status_id]          # 본문만 핀
    # keyboard 메시지(ReplyKeyboard)
    _c, _t, mk_k = board.tg.sent[1]
    assert "keyboard" in mk_k
    assert mk_k["resize_keyboard"] is True


def test_keyboard_markup_numbers_only(tmp_path):
    """버튼은 번호만(상태마크 없음) → 고정. 클릭=번호 메시지."""
    board, _ = _board(tmp_path)
    kb = board.keyboard_markup()["keyboard"]
    assert kb[0][0]["text"] == NUM_EMOJI[1]             # 번호만
    assert "⭕" not in kb[0][0]["text"]
    assert "callback_data" not in kb[0][0]


def test_refresh_skips_when_unchanged(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    board.refresh_if_changed()                          # 변화 없음
    assert board.tg.edited == []


def test_refresh_edits_status_text_only(tmp_path):
    """refresh → 본문 editMessageText(text만, markup 없음)."""
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    reg.set_status(1, "busy")
    board.refresh_if_changed()
    assert len(board.tg.edited) == 1
    _c, mid, text, mk = board.tg.edited[0]
    assert mid == board.status_id
    assert mk is None                                    # markup 없음(edit 가능)
    assert "📝" in text


def test_pending_num_shows_hourglass(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.pending_num = 1
    assert f"{NUM_EMOJI[1]}.⏳" in board.status_text()


def test_pending_priority_over_busy(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    reg.set_status(1, "busy")
    board.pending_num = 1
    assert board._mark_for(reg.get(1), 1) == "⏳"


def test_refresh_propagates_pending(tmp_path):
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    board.refresh_if_changed(pending_num=1)              # ⏳
    _c, _m, text, _mk = board.tg.edited[-1]
    assert "⏳" in text
    board.tg.edited.clear()
    board.refresh_if_changed(pending_num=None)           # ⏳ 해제 → ⭕
    _c, _m, text, _mk = board.tg.edited[-1]
    assert f"{NUM_EMOJI[1]}.⭕" in text


def test_refresh_repins_on_edit_failure(tmp_path):
    """본문 edit 실패(무효) → 자동 repin(새 status+keyboard)."""
    board, reg = _board(tmp_path)
    reg.claim_slot("s1", hwnd=1, pid=1, cwd="c", started_at="t")
    board.create()
    old_sid = board.status_id
    sent_before = len(board.tg.sent)

    def boom(*a, **k):
        raise RuntimeError("400 can't be edited")
    board.tg.edit_message_text = boom

    reg.set_status(1, "busy")
    board.refresh_if_changed()                           # edit 실패 → repin
    assert len(board.tg.sent) == sent_before + 2         # status + keyboard 재생성
    assert board.status_id != old_sid
    assert board.tg.pinned[-1] == board.status_id
