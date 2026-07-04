"""TelegramClient.send() 의 4096자 청크 분할 회귀 테스트.

분할 없이 그대로 보내면 텔레그램이 400 Bad Request 로 통째로 거부하고,
plain 폴백도 길이가 그대로라 재실패 → 회신이 유실된다(2026-07-04 발견).
"""
from imadhd.telegram_api.client import TelegramClient, MAX_TG_TEXT


def _client(calls):
    tg = TelegramClient(token="t", offset_path="/tmp/offset.txt", allowed_chat_id="1")

    def fake_api(method, data=None, timeout=30):
        calls.append((method, data))
        return {"result": {"message_id": len(calls)}}

    tg._api = fake_api
    return tg


def test_short_text_sends_single_call_with_parse_mode():
    calls = []
    tg = _client(calls)
    msg_id = tg.send("1", "짧은 메시지", parse_mode="HTML")
    assert len(calls) == 1
    assert calls[0][1]["text"] == "짧은 메시지"
    assert calls[0][1]["parse_mode"] == "HTML"
    assert msg_id == 1


def test_long_text_splits_into_multiple_calls_without_parse_mode():
    calls = []
    tg = _client(calls)
    long_text = "가" * (MAX_TG_TEXT * 2 + 100)
    tg.send("1", long_text, parse_mode="HTML")
    assert len(calls) == 3
    # 분할 시 태그 깨짐 방지를 위해 parse_mode 는 버려야 함
    assert all("parse_mode" not in data for _, data in calls)
    rejoined = "".join(data["text"] for _, data in calls)
    assert rejoined == long_text


def test_long_text_reply_markup_only_on_last_chunk():
    calls = []
    tg = _client(calls)
    long_text = "나" * (MAX_TG_TEXT + 1)
    markup = {"inline_keyboard": []}
    tg.send("1", long_text, reply_markup=markup)
    assert len(calls) == 2
    assert "reply_markup" not in calls[0][1]
    assert calls[1][1]["reply_markup"] == markup


def test_send_returns_last_chunk_message_id():
    calls = []
    tg = _client(calls)
    long_text = "다" * (MAX_TG_TEXT + 1)
    msg_id = tg.send("1", long_text)
    assert msg_id == len(calls)
