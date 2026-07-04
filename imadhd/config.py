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
    allow_any_chat: bool = False  # dev 전용: 모든 chat 허용(IMADHD_ALLOW_ANY_CHAT=1). 공개 봇 금지.

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

        # fail-closed: 공개 봇 보안. allowed_chat_id 도 없고 ALLOW_ANY 도 아니면 기동 거부.
        # 봇 토큰만 있으면 누구나 터미널 제어 가능 → chat_id 화이트리스트 필수.
        allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip() or None
        allow_any = os.environ.get("IMADHD_ALLOW_ANY_CHAT", "").strip().lower() in {"1", "true", "yes"}
        if not allowed and not allow_any:
            raise RuntimeError(
                "TELEGRAM_ALLOWED_CHAT_ID required (public bot security). "
                "Set your Telegram user id (get it from @userinfobot), "
                "or set IMADHD_ALLOW_ANY_CHAT=1 for local dev only."
            )

        return cls(
            bot_token=token,
            allowed_chat_id=allowed,
            max_slots=int(os.environ.get("IMADHD_MAX_SLOTS", "6")),
            data_dir=data_dir,
            transport=os.environ.get("IMADHD_TRANSPORT", "sendkeys_win").strip() or "sendkeys_win",
            reply_marker=os.environ.get("IMADHD_REPLY_MARKER", "[A.D.H.D]").strip() or "[A.D.H.D]",
            allow_any_chat=allow_any,
        )

    # 편의 경로
    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"

    @property
    def offset_path(self) -> Path:
        return self.data_dir / "offset.txt"

    @property
    def heartbeat_path(self) -> Path:
        return self.data_dir / "heartbeat.txt"
