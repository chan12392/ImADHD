"""텔레그램 Bot API 최소 래퍼. 의존성 0 (urllib).

- getUpdates(long_poll) + offset 영구 저장
- sendMessage
"""
from __future__ import annotations

import json
import urllib.error
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
        # message(본문/ReplyKeyboard 클릭) + callback_query(인라인 버튼 탭) 수신.
        # callback_query = AskUserQuestion 인라인 답변 버튼용.
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        offset = self._load_offset()
        if offset:
            params["offset"] = offset
        resp = self._api("getUpdates", params, timeout=timeout + 10)
        result = resp.get("result", []) or []
        if result:
            self._save_offset(result[-1].get("update_id", 0) + 1)
        return result

    def send(self, chat_id: str, text: str, reply_markup: dict | None = None,
             parse_mode: str | None = None) -> int | None:
        """메시지 전송. 반환=message_id (pin 용). reply_markup=키보드. parse_mode='Markdown'|'HTML'."""
        if not chat_id:
            return None
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        resp = self._api("sendMessage", data, timeout=10)
        return resp.get("result", {}).get("message_id")

    def edit_message_text(self, chat_id: str, message_id: int, text: str,
                          reply_markup: dict | None = None) -> None:
        if not chat_id or not message_id:
            return
        data = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            data["reply_markup"] = reply_markup
        try:
            self._api("editMessageText", data, timeout=10)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            # "not modified"(내용 동일, 정상)만 삼킴. 그 외 400(can't be edited/
            # not found = 핀 무효)는 raise → 상위(PinBoard)에서 repin 유도.
            if e.code == 400 and "not modified" in body:
                return
            raise

    def edit_message_reply_markup(self, chat_id: str, message_id: int,
                                  reply_markup: dict | None) -> None:
        """ReplyKeyboard 갱신: 메시지 텍스트 유지, 키보드만 교체."""
        if not chat_id or not message_id or not reply_markup:
            return
        data = {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        try:
            self._api("editMessageReplyMarkup", data, timeout=10)
        except urllib.error.HTTPError as e:
            # 400 "message is not modified" = 동일(정상). best-effort.
            if e.code != 400:
                raise

    def answer_callback(self, callback_query_id: str, text: str) -> None:
        """인라인 버튼 클릭 토스트 응답(callback_query). answerCallbackQuery."""
        if not callback_query_id:
            return
        self._api("answerCallbackQuery",
                  {"callback_query_id": callback_query_id, "text": text, "show_alert": False},
                  timeout=10)

    def delete_message(self, chat_id: str, message_id: int) -> None:
        """메시지 삭제. 기존 핀 교체 시 구 핀 정리용."""
        if not chat_id or not message_id:
            return
        try:
            self._api("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=10)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise

    def pin_chat_message(self, chat_id: str, message_id: int) -> None:
        if not chat_id or not message_id:
            return
        self._api("pinChatMessage",
                  {"chat_id": chat_id, "message_id": message_id, "disable_notification": True},
                  timeout=10)

    def set_my_commands(self, commands: list, scope: dict | None = None) -> dict:
        """봇 명령 메뉴 등록(setMyCommands). commands=[{command, description}, ...].
        command: 소문자/숫자/밑줄 1~32자. description: 사용자 표시(한글 OK).
        scope=None → default. private DM 은 all_private_chats 가 default 보다 우선하므로,
        DM 에도 메뉴를 띄우려면 scope={"type":"all_private_chats"} 로도 등록할 것."""
        payload: dict = {"commands": commands}
        if scope:
            payload["scope"] = scope
        return self._api("setMyCommands", payload, timeout=10)

    def delete_my_commands(self, scope: dict | None = None) -> dict:
        """해당 scope 명령 메뉴 삭제(잔재 정리). scope=None → default."""
        payload: dict = {}
        if scope:
            payload["scope"] = scope
        return self._api("deleteMyCommands", payload, timeout=10)

    def _load_offset(self) -> int:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(offset), encoding="utf-8")
