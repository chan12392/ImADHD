"""marker_capture 회신 전략 테스트. 마커 기반 본문 추출 + 말단 매칭(false trigger 방지)."""
from imadhd.reply.marker_capture import MarkerCapture
from imadhd.reply.base import ReplyPayload

MARKER = "[A.D.H.D]"


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


def test_marker_not_on_last_line_no_reply():
    """마커가 마지막 non-empty 줄 아니면 회신 X (입력 마커 echo false trigger 방지)."""
    mc = MarkerCapture(MARKER)
    rp = _payload(f"{MARKER}\n그런데 이어서 답을 달았다")  # 마커 첫 줄, 마지막엔 없음
    assert mc.should_reply(rp) is False


def test_trailing_blank_after_marker_still_replies():
    """마커 뒤 빈 줄만 있으면 마커 줄이 마지막 non-empty → 회신."""
    mc = MarkerCapture(MARKER)
    rp = _payload(f"본문.\n{MARKER}\n  \n")
    assert mc.should_reply(rp) is True
    assert mc.build_text(rp) == "본문."
