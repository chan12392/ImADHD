"""MarkerCapture 회신 전략 테스트.

새 로직(2026-07-06): 마커 의존 제거. 회신 여부 = assistant 답 있음 여부,
본문 = 답 전체. (회신 여부/길이 교정은 reply_hook이 pending 플래그+길이
게이트로 담당 — 여기선 캡처 전략만 검증.)
"""
from imadhd.reply.marker_capture import MarkerCapture
from imadhd.reply.base import ReplyPayload


def _payload(text: str) -> ReplyPayload:
    return ReplyPayload(session_id="s", transcript_path="t", assistant_text=text)


def test_empty_text_no_reply():
    assert MarkerCapture("[A.D.H.D]").should_reply(_payload("")) is False
    assert MarkerCapture("[A.D.H.D]").should_reply(_payload("   ")) is False


def test_nonempty_text_replies():
    mc = MarkerCapture("[A.D.H.D]")
    assert mc.should_reply(_payload("답변입니다")) is True


def test_build_text_returns_full_body():
    """본문 = assistant_text 전체(마커 잘라내기 없음). CC가 마커를 안 뱉으니
    회신에 표식이 섞이지 않는다."""
    mc = MarkerCapture("[A.D.H.D]")
    rp = _payload("첫 줄.\n둘째 줄.\n결론.")
    assert mc.build_text(rp) == "첫 줄.\n둘째 줄.\n결론."


def test_marker_in_body_is_kept_verbatim():
    """마커가 본문에 포함돼도 잘라내지 않고 그대로(레거시 호환 — 구버전 CC가
    마커를 뱉은 경우도 회신은 정상)."""
    mc = MarkerCapture("[A.D.H.D]")
    rp = _payload("답 [A.D.H.D]")
    assert mc.build_text(rp) == "답 [A.D.H.D]"


def test_marker_arg_ignored():
    """marker 인자는 레거시 호환용. should_reply/build_text 에 영향 없음."""
    assert MarkerCapture("").should_reply(_payload("답")) is True
    assert MarkerCapture("").build_text(_payload("답")) == "답"


def test_build_text_strips_whitespace():
    mc = MarkerCapture("[A.D.H.D]")
    assert mc.build_text(_payload("  답  \n")) == "답"
