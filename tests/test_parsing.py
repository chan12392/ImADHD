from imadhd.commands.inject_command import parse_leading_number, leading_prefix


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
