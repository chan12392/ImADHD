"""마커 기반 답변 캡처 전략.

CC 가 답변 말단에 설정된 마커(기본 '텔레그램으로 답변')를 출력하면
그 윗본문을 추출해 회신. 마커 없으면 회신 안 함(일반 터미널 응답).
"""
from __future__ import annotations

from .base import ReplyStrategy, ReplyPayload


class MarkerCapture(ReplyStrategy):
    def __init__(self, marker: str):
        self.marker = marker

    def should_reply(self, payload: ReplyPayload) -> bool:
        return self.marker in (payload.assistant_text or "")

    def build_text(self, payload: ReplyPayload) -> str:
        text = payload.assistant_text or ""
        lines = text.splitlines()
        out = []
        for line in lines:
            if self.marker in line:
                before = line.split(self.marker)[0].rstrip()
                if before:
                    out.append(before)
                break
            out.append(line)
        return "\n".join(out).strip()
