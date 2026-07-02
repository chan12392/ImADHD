"""설정 로드. 시크릿은 오직 여기서만 환경변수/.env 에서 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv  # optional
except Exception:  # pragma: no cover
    def load_dotenv(*a, **k):
        return False


def _data_dir_default() -> Path:
    return Path.home() / ".imadhd"


@dataclass
class Settings:
    bot_token: str
    allowed_chat_id: str | None
    max_slots: int
    data_dir: Path
    transport: str
    reply_marker: str

    @classmethod
    def load(cls, env_path: str | os.PathLike | None = None) -> "Settings":
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()  # cwd / .env

        dd = os.environ.get("IMADHD_DATA_DIR", "").strip()
        data_dir = Path(dd) if dd else _data_dir_default()
        data_dir.mkdir(parents=True, exist_ok=True)

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing. Set it in .env (see .env.example).")

        return cls(
            bot_token=token,
            allowed_chat_id=(os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip() or None),
            max_slots=int(os.environ.get("IMADHD_MAX_SLOTS", "6")),
            data_dir=data_dir,
            transport=os.environ.get("IMADHD_TRANSPORT", "sendkeys_win").strip() or "sendkeys_win",
            reply_marker=os.environ.get("IMADHD_REPLY_MARKER", "텔레그램으로 답변").strip() or "텔레그램으로 답변",
        )

    # 편의 경로
    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"

    @property
    def offset_path(self) -> Path:
        return self.data_dir / "offset.txt"
