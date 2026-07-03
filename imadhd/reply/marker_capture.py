"""마커 기반 답변 캡처 전략.

CC 가 답변 **마지막 줄**에 설정된 마커(기본 '[A.D.H.D]')를 출력하면
그 윗본문을 추출해 회신. 마커 없으면 회신 안 함(일반 터미널 응답).

말단(non-empty 마지막 줄) 매칭 — 입력 마커([A.D.H.D])를 CC가 본문 도중
echo 해도 false trigger 안 남(오직 마지막 줄만 회신 트리거).
"""
from __future__ import annotations

from .base import ReplyStrategy, ReplyPayload


class MarkerCapture(ReplyStrategy):
    def __init__(self, marker: str):
        self.marker = marker

    @staticmethod
    def _last_nonempty_line(text: str) -> str:
        for line in reversed((text or "").splitlines()):
            if line.strip():
                return line
        return ""

    def should_reply(self, payload: ReplyPayload) -> bool:
        last = self._last_nonempty_line(payload.assistant_text)
        return bool(last) and self.marker in last

    def build_text(self, payload: ReplyPayload) -> str:
        text = payload.assistant_text or ""
        lines = text.splitlines()
        # 마지막 non-empty 줄 인덱스
        last_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                last_idx = i
                break
        if last_idx is None:
            return ""
        last_line = lines[last_idx]
        if self.marker in last_line:
            before = last_line.split(self.marker)[0].rstrip()
            kept = lines[:last_idx]
            if before:
                kept.append(before)
        else:
            kept = lines
        return "\n".join(kept).strip()
