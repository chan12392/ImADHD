"""reply_hook 순수 로직 테스트.

회신 결정: 마지막 user 메시지의 reply_marker([A.D.H.D]) 유무로 출처 판정.
마커 있으면 텔레그램 인입 답 → 회신. 없으면 데스크톱 직접 → 스킵(2026-07-09).
"""
from imadhd.hooks.reply_hook import (
    reply_too_long,
    last_user_text_from_entries,
    _is_external_user_message,
    _origin_has_marker,
    _extract_images,
    _last_assistant_images,
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


# ---------- 출처 마커 게이트 (2026-07-09: TG 답만 회신) ----------

def test_origin_has_marker_true_for_tg_inject():
    """텔레그램 주입(inject_command가 마커 부착) → 회신."""
    last_user = f"작업해줘 {MARKER}"
    assert _origin_has_marker(last_user, MARKER) is True


def test_origin_has_marker_false_for_desktop_direct():
    """데스크톱 앱/터미널 직접 타이핑(마커 없음) → 회신 스킵."""
    assert _origin_has_marker("그냥 직접 친 질문", MARKER) is False


def test_origin_has_marker_false_for_empty():
    assert _origin_has_marker("", MARKER) is False
    assert _origin_has_marker(None, MARKER) is False  # type: ignore[arg-type]


def test_origin_has_marker_via_entries_pipeline():
    """entries → last_user_text_from_entries → _origin_has_marker 전체 파이프라인.
    tool_result-only user round 를 건너뛰고 진짜 user 발화에서 마커 판정."""
    entries = [
        _user(f"텔레그램에서 보낸 요청 {MARKER}"),
        _assistant("작업 중"),
        _user_tool_result_only(),
        _assistant("완료"),
    ]
    last_user = last_user_text_from_entries(entries)
    assert _origin_has_marker(last_user, MARKER) is True


def test_origin_has_marker_desktop_via_entries_pipeline():
    """데스크톱 직접 작업 entries → 마커 없음 → 회신 스킵."""
    entries = [
        _user("데스크톱에서 직접 친 질문"),
        _assistant("답변"),
    ]
    last_user = last_user_text_from_entries(entries)
    assert _origin_has_marker(last_user, MARKER) is False


# ---------- image 추출 (CC→TG) ----------

import base64 as _b64


def _img_block(b64_data, media="image/png"):
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": b64_data}}


def _assistant_with_image(b64, text=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    content.append(_img_block(b64))
    return {"message": {"role": "assistant", "content": content}}


def test_extract_images_decodes_base64_png():
    raw = b"\x89PNG\r\n\x1a\n" + b"payload"
    imgs = _extract_images([_img_block(_b64.b64encode(raw).decode())])
    assert len(imgs) == 1
    assert imgs[0]["data"] == raw
    assert imgs[0]["ext"] == "png"
    assert imgs[0]["media_type"] == "image/png"


def test_extract_images_jpeg_uses_jpg_ext():
    raw = b"\xff\xd8\xff\xe0jpeg"
    imgs = _extract_images([_img_block(_b64.b64encode(raw).decode(), "image/jpeg")])
    assert imgs[0]["ext"] == "jpg"


def test_extract_images_skips_url_source_bad_b64_and_non_image():
    url_block = {"type": "image", "source": {"type": "url", "url": "http://x/a.png"}}
    bad_block = {"type": "image", "source": {"type": "base64", "data": "!!!notb64!!!"}}
    text_block = {"type": "text", "text": "hi"}
    assert _extract_images([url_block, bad_block, text_block]) == []


def test_extract_images_empty_for_string_content():
    assert _extract_images("plain string") == []


def test_last_assistant_images_picks_last_assistant_entry():
    raw1 = b"img1"
    raw2 = b"img2-data-longer"
    entries = [
        _assistant_with_image(_b64.b64encode(raw1).decode(), text="첫 답"),
        {"message": {"role": "user", "content": "다음"}},
        _assistant_with_image(_b64.b64encode(raw2).decode()),
    ]
    imgs = _last_assistant_images(entries)
    assert len(imgs) == 1
    assert imgs[0]["data"] == raw2


def test_last_assistant_images_empty_when_text_only():
    assert _last_assistant_images([_assistant("텍스트만")]) == []
