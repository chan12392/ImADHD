"""봇 명령 메뉴(setMyCommands) 자동 등록.

설치(setup) 단계에서 호출 → 텔레그램 봇의 `/` 명령 자동완성 메뉴에
`/1`~`/N` + `/list` 등록. 각 `/N` 클릭 = N번 터미널 선택모드(pending).
"""
from __future__ import annotations

from pathlib import Path


def build_commands(max_slots: int = 6) -> list[dict]:
    """등록할 명령 리스트. 순서 = 텔레그램 `/` 메뉴 표시 순서.

      `/1`~`/N` : N번 터미널로 메시지 전송   (InjectCommand — 즉시주입/pending)
      `/list`   : 활성 터미널 목록            (ListCommand)
      `/new N`  : N번 터미널 새 대화(/clear)  (NewCommand)
      `/help`   : 명령 도움말                  (HelpCommand)
      `/pin`    : 상태 보드 핀 새로고침        (PinCommand)
    """
    cmds = [
        {"command": str(n), "description": f"{n}번 터미널로 메시지 전송"}
        for n in range(1, max_slots + 1)
    ]
    cmds.append({"command": "list", "description": "활성 터미널 목록 보기"})
    cmds.append({"command": "new", "description": "N번 터미널 새 대화(/clear)  예: /new 1"})
    cmds.append({"command": "help", "description": "명령 도움말"})
    cmds.append({"command": "pin", "description": "상태 보드 핀 새로고침"})
    return cmds


def register(token: str, max_slots: int = 6):
    """해당 토큰 봇에 setMyCommands 호출. 반환=Telegram API 응답(dict).

      1) default + all_private_chats 둘 다 등록 — DM(private)은 all_private_chats 가
         default 보다 우선하므로, default 만 등록하면 DM 에서 다른 잔재(예: 이전 channels
         플러그인 명령)에 덮힘.
      2) group/administrator scope 잔재 정리(delete).
    """
    import tempfile
    from .telegram_api.client import TelegramClient

    off = Path(tempfile.gettempdir()) / "imadhd_setup_offset.txt"
    tg = TelegramClient(token, off, None)
    cmds = build_commands(max_slots)
    tg.set_my_commands(cmds)                                   # default
    tg.set_my_commands(cmds, scope={"type": "all_private_chats"})  # DM 우선 scope
    tg.delete_my_commands(scope={"type": "all_group_chats"})
    tg.delete_my_commands(scope={"type": "all_chat_administrators"})
    return tg.set_my_commands(cmds)  # 최종 default 결과 반환(호환)
