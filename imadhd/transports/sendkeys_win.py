"""Windows ctypes 기반 send_keys transport.

기존 $HOME/programs/send_keys_to_claude.py 로직 이식 + 확장:
  - --hwnd 직접 지정
  - --bg (백그라운드 PostMessage, 베타)
  - IsWindow 사전체크

Windows 전용. 타 OS 에서는 미임포트(ImportError) → config 에서 다른 transport 선택.
"""
from __future__ import annotations

from .base import Transport, InjectResult


class SendKeysWinTransport(Transport):
    def inject(self, target: dict, text: str, background: bool = False) -> InjectResult:
        raise NotImplementedError("implemented in plan step")

    def is_alive(self, target: dict) -> bool:
        raise NotImplementedError("implemented in plan step")
