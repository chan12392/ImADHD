"""TelegramClient.send() 의 4096자 청크 분할 회귀 테스트.

분할 없이 그대로 보내면 텔레그램이 400 Bad Request 로 통째로 거부하고,
plain 폴백도 길이가 그대로라 재실패 → 회신이 유실된다(2026-07-04 발견).
send() 는 모든 청크의 message_id 리스트를 반환 — reply_hook 이 각 청크를
같은 슬롯에 매핑(2026-07-06).
"""
import pytest

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
    ids = tg.send("1", "짧은 메시지", parse_mode="HTML")
    assert len(calls) == 1
    assert calls[0][1]["text"] == "짧은 메시지"
    assert calls[0][1]["parse_mode"] == "HTML"
    assert ids == [1]


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


def test_send_returns_all_chunk_message_ids():
    """긴 회신 = 모든 청크 id 리스트 반환 (reply_hook 전 청크 매핑용)."""
    calls = []
    tg = _client(calls)
    long_text = "다" * (MAX_TG_TEXT + 1)   # 2 청크
    ids = tg.send("1", long_text)
    assert ids == [1, 2]
    assert len(calls) == 2


def test_send_returns_empty_list_for_empty_chat():
    ids = TelegramClient("t", "/tmp/x.txt", "1").send("", "x")
    assert ids == []


def test_download_file_writes_bytes_and_creates_parent(monkeypatch, tmp_path):
    """TG→CC 이미지 수신: getFile → 다운로드 → 부모 디렉토리 자동 생성."""
    import imadhd.telegram_api.client as cli_mod
    tg = TelegramClient(token="T", offset_path=tmp_path / "off.txt", allowed_chat_id=None)
    tg._api = lambda method, data=None, timeout=30: {"result": {"file_path": "photos/file.jpg"}}

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"JPEGBYTES"

    monkeypatch.setattr(cli_mod.urllib.request, "urlopen",
                        lambda req, timeout=60: FakeResp())
    dest = tmp_path / "inbox" / "tg_123.jpg"   # 부모 미존재 → 자동 생성 검증
    p = tg.download_file("fid_abc", dest)
    assert p == dest
    assert dest.read_bytes() == b"JPEGBYTES"
    assert dest.parent.exists()


def test_download_file_missing_file_path_raises(monkeypatch, tmp_path):
    """getFile 응답에 file_path 없으면 RuntimeError(fail-loud)."""
    tg = TelegramClient(token="T", offset_path=tmp_path / "off.txt", allowed_chat_id=None)
    tg._api = lambda method, data=None, timeout=30: {"result": {}}
    with pytest.raises(RuntimeError):
        tg.download_file("fid", tmp_path / "x.jpg")
