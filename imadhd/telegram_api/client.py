"""텔레그램 Bot API 최소 래퍼. 의존성 0 (urllib).

- getUpdates(long_poll) + offset 영구 저장
- sendMessage
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


class TelegramClient:
    def __init__(self, token: str, offset_path: Path, allowed_chat_id: str | None = None):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.offset_path = Path(offset_path)
        self.allowed_chat_id = allowed_chat_id

    def _api(self, method: str, data=None, timeout: int = 30) -> dict:
        url = f"{self.base}/{method}"
        if data is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_updates(self, timeout: int = 30) -> list:
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        offset = self._load_offset()
        if offset:
            params["offset"] = offset
        resp = self._api("getUpdates", params, timeout=timeout + 10)
        result = resp.get("result", []) or []
        if result:
            self._save_offset(result[-1].get("update_id", 0) + 1)
        return result

    def send(self, chat_id: str, text: str) -> None:
        if not chat_id:
            return
        self._api("sendMessage", {"chat_id": chat_id, "text": text}, timeout=10)

    def _load_offset(self) -> int:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(offset), encoding="utf-8")
