"""봇 명령 메뉴(setMyCommands) 자동 등록.

설치(setup) 단계에서 호출 → 텔레그램 봇의 `/` 명령 자동완성 메뉴에
`/1`~`/N` + `/list` 등록. 각 `/N` 클릭 = N번 터미널 선택모드(pending).
"""
from __future__ import annotations

from pathlib import Path


def build_commands(max_slots: int = 6) -> list[dict]:
    """등록할 명령 리스트.
    `/1`~`/N`: "N번 터미널로 메시지 전송" (inject_command 에서 즉시주입/pending 둘 다 지원)
    `/list` : "활성 터미널 목록" (ListCommand TRIGGERS 에 이미 /list 있음)
    """
    cmds = [
        {"command": str(n), "description": f"{n}번 터미널로 메시지 전송"}
        for n in range(1, max_slots + 1)
    ]
    cmds.append({"command": "list", "description": "활성 터미널 목록 보기"})
    return cmds


def register(token: str, max_slots: int = 6):
    """해당 토큰 봇에 setMyCommands 호출. 반환=Telegram API 응답(dict)."""
    import tempfile
    from .telegram_api.client import TelegramClient

    # setup 용 offset 경로(사용 안 함, 더미). client 생성자 요구.
    off = Path(tempfile.gettempdir()) / "imadhd_setup_offset.txt"
    tg = TelegramClient(token, off, None)
    return tg.set_my_commands(build_commands(max_slots))
