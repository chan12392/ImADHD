from imadhd.commands.inject_command import parse_leading_number, leading_emoji
from imadhd.reply.marker_capture import MarkerCapture, ReplyPayload


def test_parse_emoji_number():
    assert parse_leading_number("3️⃣ check logs") == 3
    assert parse_leading_number("1️⃣") == 1


def test_parse_no_emoji():
    assert parse_leading_number("check logs") is None
    assert parse_leading_number("") is None


def test_leading_emoji_str():
    assert leading_emoji("2️⃣ hi") == "2️⃣"
    assert leading_emoji("hi") == ""


def test_marker_strips_marker_and_after():
    mc = MarkerCapture("텔레그램으로 답변")
    p = ReplyPayload("s", "x", "line1\nline2\n텔레그램으로 답변\nshould-drop")
    assert mc.build_text(p) == "line1\nline2"


def test_marker_inline_keeps_before():
    mc = MarkerCapture("텔레그램으로 답변")
    p = ReplyPayload("s", "x", "done 텔레그램으로 답변")
    assert mc.build_text(p) == "done"


def test_marker_should_reply():
    mc = MarkerCapture("텔레그램으로 답변")
    assert mc.should_reply(ReplyPayload("s", "x", "hi 텔레그램으로 답변")) is True
    assert mc.should_reply(ReplyPayload("s", "x", "hi")) is False
