"""transports: 터미널 입력 방식 (확장 포인트)."""
from .base import Transport


def make_transport(name: str) -> Transport:
    """설정(settings.transport) → Transport 인스턴스.

    새 입력 방식(tmux/pty/ahk 등) 추가 시 이 함수에 branch만 추가.
    core/commands 변경 없음 (Transport ABC 만족하면 자동 인식).
    """
    if name == "sendkeys_win":
        from .sendkeys_win import SendKeysWinTransport
        return SendKeysWinTransport()
    raise ValueError(f"unknown transport: {name!r} (settings.transport / IMADHD_TRANSPORT)")


__all__ = ["Transport", "make_transport"]
