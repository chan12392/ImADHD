"""reply_hook 순수 로직 테스트.

2026-07-06 전환: 마커 echo 의존 제거. marker_missing → reply_too_long(길이 게이트).
회신 결정은 reply_hook main이 pending 플래그로 하므로 여기선 길이 판정만.
"""
from imadhd.hooks.reply_hook import (
    reply_too_long,
    last_user_text_from_entries,
    _is_external_user_message,
    REPLY_HARD_LIMIT,
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


# ---------- reply_too_long ----------

def test_short_reply_not_too_long():
    assert reply_too_long("짧은 답") is False


def test_reply_under_hard_limit_ok():
    assert reply_too_long("x" * REPLY_HARD_LIMIT) is False


def test_reply_over_hard_limit_blocked():
    assert reply_too_long("x" * (REPLY_HARD_LIMIT + 1)) is True


def test_empty_reply_not_too_long():
    assert reply_too_long("") is False
    assert reply_too_long(None) is False  # type: ignore[arg-type]


# ---------- transcript user 발화 추출 ----------

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
