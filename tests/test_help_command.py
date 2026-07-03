"""/help 핸들러 단위 테스트."""
from imadhd.commands.base import Message, CommandContext
from imadhd.commands.help_command import HelpCommand, HELP_TEXT


class FakeTG:
    def __init__(self):
        self.sent = []
    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


def _ctx():
    return CommandContext(settings=None, registry=None, transport=None, telegram=FakeTG())


def test_help_match_variants():
    c = HelpCommand()
    for t in ["/help", "/HELP", "/Help", "/도움", "/?", "  /help  "]:
        assert c.match(Message("1", t, {})) is True, t


def test_help_no_match():
    c = HelpCommand()
    for t in ["/list", "/pin", "/new 1", "1️⃣", "안녕", "/helpp"]:
        assert c.match(Message("1", t, {})) is False, t


def test_help_sends_text():
    ctx = _ctx()
    HelpCommand().handle(Message("9", "/help", {}), ctx)
    assert len(ctx.telegram.sent) == 1
    assert ctx.telegram.sent[0] == ("9", HELP_TEXT)
