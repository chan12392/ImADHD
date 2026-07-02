"""marker_capture 회신 전략 테스트. 마커 기반 본문 추출 정상 입증."""
from imadhd.reply.marker_capture import MarkerCapture
from imadhd.reply.base import ReplyPayload

MARKER = "텔레그램으로 답변"


def _payload(text: str) -> ReplyPayload:
    return ReplyPayload(session_id="s", transcript_path="t", assistant_text=text)


def test_marker_absent_no_reply():
    mc = MarkerCapture(MARKER)
    assert mc.should_reply(_payload("그냥 답변입니다")) is False


def test_single_line_body_before_marker():
    mc = MarkerCapture(MARKER)
    rp = _payload(f"지금 오후 12시 39분입니다. {MARKER}")
    assert mc.should_reply(rp) is True
    assert mc.build_text(rp) == "지금 오후 12시 39분입니다."


def test_multiline_body_marker_on_last_line():
    mc = MarkerCapture(MARKER)
    text = f"첫 줄 요약.\n둘째 줄 상세.\n셋째 줄 결론.\n{MARKER}"
    rp = _payload(text)
    assert mc.build_text(rp) == "첫 줄 요약.\n둘째 줄 상세.\n셋째 줄 결론."


def test_marker_mid_line_drops_rest():
    mc = MarkerCapture(MARKER)
    rp = _payload(f"답변 본문. {MARKER} 이건 잘려야 함")
    assert mc.build_text(rp) == "답변 본문."


def test_marker_only_line_yields_prior_body():
    mc = MarkerCapture(MARKER)
    rp = _payload(f"본문입니다.\n{MARKER}")
    assert mc.build_text(rp) == "본문입니다."


def test_empty_body_before_marker_returns_empty():
    mc = MarkerCapture(MARKER)
    rp = _payload(f"{MARKER}")
    assert mc.build_text(rp) == ""
