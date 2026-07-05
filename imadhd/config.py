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
        # IMADHD_ENV_FILE: 공유(gdrive 등) repo 경로와 머신별 설정을 분리하기 위한
        # 명시적 오버라이드. 여러 머신이 같은 repo 경로를 공유(예: gdrive 동기화)
        # 하면 cwd 탐색이 서로 다른 머신의 .env 를 덮어쓸 위험이 있다
        # (2026-07-05 실사고: 오라클 클로이 설정이 gdrive 동기화로 데스크톱
        # 백호 .env 를 덮어씀). env_path 인자보다 우선.
        forced = os.environ.get("IMADHD_ENV_FILE", "").strip()
        if forced:
            load_dotenv(forced, override=True)
        elif env_path:
            load_dotenv(env_path)
        else:
            # ~/.imadhd/env (0600, hook/router 공통) 우선 로드 → cwd/.env 보강.
            # settings.json global env 대신: CC 세션/하위 프로세스에 토큰 확산 방지.
            user_env = _data_dir_default() / "env"
            if user_env.exists():
                load_dotenv(user_env, override=True)
            # override=True: ~/.imadhd/env 와 repo .env 가 ambient env 보다 우선.
            # 2026-07-06 실사고: pm2 daemon/터미널 부모 체인에 IMADHD_TRANSPORT=
            # sendkeys_win 이 세션 레벨로 깔려 있어 override=False(default)면
            # .env 의 pipe_win 이 무시되고 sendkeys 로 회귀(포커스 강제 주입).
            # 설계 의도(ambient 확산 방지, 위 주석)에 맞게 .env 를 권위로.
            load_dotenv(override=True)  # cwd / .env

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
