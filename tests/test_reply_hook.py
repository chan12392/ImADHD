"""reply_hook 순수 로직 테스트. 마커 인입 turn 에서 응답 마커 누락 감지."""
from imadhd.hooks.reply_hook import (
    marker_missing,
    last_user_text_from_entries,
    _is_external_user_message,
)

MARKER = "[A.D.H.D]"


def _user(text):
    return {"message": {"role": "user", "content": text}}


def _user_tool_result_only():
    return {"message": {"role": "user", "content": [
        {"type": "tool_result", "content": "ok"},
    ]}}


def _assistant(text):
    return {"message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def test_no_marker_in_user_message_not_blocked():
    assert marker_missing("일반 작업 요청", "작업 끝났습니다", MARKER) is False


def test_marker_in_user_but_missing_in_reply_blocked():
    assert marker_missing(f"확인해줘 {MARKER}", "확인했습니다.", MARKER) is True


def test_marker_in_user_and_present_in_reply_ok():
    assert marker_missing(f"확인해줘 {MARKER}", f"확인했습니다.\n{MARKER}", MARKER) is False


def test_marker_present_but_not_on_last_line_still_blocked():
    """마커가 응답 도중에만 있고 마지막 줄엔 없으면 여전히 차단(echo false positive 방지 유지)."""
    text = f"{MARKER} 이런 요청이었죠.\n네 처리했습니다."
    assert marker_missing(f"해줘 {MARKER}", text, MARKER) is True


def test_last_user_text_skips_tool_result_only_round():
    entries = [
        _user(f"진짜 요청 {MARKER}"),
        _assistant("작업 중"),
        _user_tool_result_only(),
        _assistant("작업 끝"),
    ]
    assert MARKER in last_user_text_from_entries(entries)


def test_is_external_user_message_true_for_text():
    assert _is_external_user_message(_user("안녕")) is True


def test_is_external_user_message_false_for_tool_result_only():
    assert _is_external_user_message(_user_tool_result_only()) is False
