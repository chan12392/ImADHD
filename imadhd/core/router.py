"""라우터 메인루프: 텔레그램 롱폴 → 명령 매칭 → 주입/회신.

확장: commands 리스트에 Command 추가하면 자동으로 새 명령 인식.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings


def run(settings: "Settings") -> None:
    """TODO: getUpdates 루프, offset 영구 저장, 명령 디스패치."""
    raise NotImplementedError("implemented in plan step")
