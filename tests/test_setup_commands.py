"""setup_commands.build_commands 단위 테스트 (setMyCommands 등록 전 검증)."""
import re
from imadhd.setup_commands import build_commands


def test_build_commands_6():
    cmds = build_commands(6)
    assert [c["command"] for c in cmds] == [
        "1", "2", "3", "4", "5", "6",
        "list", "new", "open", "close", "stop", "help", "pin",
    ]
    assert cmds[0]["description"] == "1번 터미널로 메시지 전송"
    assert cmds[-1]["command"] == "pin"


def test_build_commands_respects_max():
    cmds = build_commands(3)
    assert len(cmds) == 10                      # 1~3 + list/new/open/close/stop/help/pin
    assert cmds[2]["command"] == "3"


def test_commands_valid_telegram_format():
    """command: 소문자/숫자/밑줄 1~32자 (텔레그랸 규칙). description 비어있지 않을 것."""
    for c in build_commands(6):
        assert re.match(r"^[a-z0-9_]{1,32}$", c["command"]), c
        assert c["description"].strip()
