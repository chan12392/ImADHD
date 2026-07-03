from imadhd.commands.inject_command import parse_leading_number, leading_prefix
from imadhd.reply.marker_capture import MarkerCapture, ReplyPayload


def test_parse_emoji_number():
    assert parse_leading_number("3️⃣ check logs") == 3
    assert parse_leading_number("1️⃣") == 1


def test_parse_slash_number():
    assert parse_leading_number("/1 check logs") == 1
    assert parse_leading_number("/6") == 6
    assert parse_leading_number("/1본문없음공백") == 1      # 공백 없어도 허용
    assert parse_leading_number("/10") is None              # 두자리 방지
    assert parse_leading_number("/x") is None


def test_parse_no_emoji():
    assert parse_leading_number("check logs") is None
    assert parse_leading_number("") is None


def test_leading_prefix_str():
    assert leading_prefix("2️⃣ hi") == "2️⃣"
    assert leading_prefix("/1 hi") == "/1"
    assert leading_prefix("hi") == ""


def test_marker_on_last_line_strips_it():
    """마커가 마지막 non-empty 줄 → 마커 줄 제거, 윗본문 유지."""
    mc = MarkerCapture("[A.D.H.D]")
    p = ReplyPayload("s", "x", "line1\nline2\n[A.D.H.D]")
    assert mc.should_reply(p) is True
    assert mc.build_text(p) == "line1\nline2"


def test_marker_inline_keeps_before():
    mc = MarkerCapture("[A.D.H.D]")
    p = ReplyPayload("s", "x", "done [A.D.H.D]")
    assert mc.build_text(p) == "done"


def test_marker_should_reply():
    mc = MarkerCapture("[A.D.H.D]")
    assert mc.should_reply(ReplyPayload("s", "x", "hi [A.D.H.D]")) is True
    assert mc.should_reply(ReplyPayload("s", "x", "hi")) is False
    # 마커가 마지막 줄 아니면(뒤에 이어 말함) → 회신 X (false trigger 방지)
    assert mc.should_reply(ReplyPayload("s", "x", "[A.D.H.D]\nsomething after")) is False
