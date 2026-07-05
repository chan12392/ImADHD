"""회신 캡처 전략 (회신 대상 턴 = 전체 assistant 답변 회신).

회신 여부/본문은 더 이상 마커([A.D.H.D])에 의존하지 않는다:
  - 회신 여부: reply_hook 이 marker_pending 플래그(inject 시점 세팅)로
    "이 턴은 텔레그램 인입이었다"를 판정. 거기에 길이 게이트(1200자)가
    짧게 다시 쓰기를 1회 요청할 수 있다.
  - 회신 본문: assistant 답변 전체(마커 잘라내기 없음). CC가 마커를
    출력하지 않으니 회신에 표식이 섞이지 않는다.

클래스명 MarkerCapture 는 레거시 import 호환용. marker 인자는 무시.
"""
from __future__ import annotations

from .base import ReplyStrategy, ReplyPayload


class MarkerCapture(ReplyStrategy):
    """회신 대상 턴이면 무조건 회신. 본문 = assistant_text 전체."""

    def __init__(self, marker: str = ""):
        # marker 인자는 레거시 호환용. 더 이상 사용하지 않는다.
        self.marker = marker

    def should_reply(self, payload: ReplyPayload) -> bool:
        return bool((payload.assistant_text or "").strip())

    def build_text(self, payload: ReplyPayload) -> str:
        return (payload.assistant_text or "").strip()
