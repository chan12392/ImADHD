"""텔레그램 Bot API 최소 래퍼. 의존성 0 (urllib).

- getUpdates(long_poll) + offset 영구 저장
- sendMessage
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# 텔레그램 sendMessage 텍스트 한도(4096) 대비 여유. 초과 시 400 Bad Request로
# 통째로 실패하고, reply_hook 의 plain 폴백도 길이가 그대로라 재실패 →
# 예외가 삼켜지지 않으면 Stop 훅이 죽어 회신 자체가 안 감(2026-07-04 발견).
MAX_TG_TEXT = 4000


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

    def download_file(self, file_id: str, dest_path) -> Path:
        """텔레그램 파일 다운로드(TG→CC 이미지 수신용). getFile → file_path → 다운로드.

        dest_path=저장 경로(Path|str). 부모 디렉토리 자동 생성. 반환=저장 Path.
        텔레그램 photo는 항상 jpg(확장자 호출자 책임)."""
        resp = self._api("getFile", {"file_id": file_id}, timeout=30)
        file_path = (resp.get("result") or {}).get("file_path")
        if not file_path:
            raise RuntimeError("getFile: file_path 없음")
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                with urllib.request.urlopen(req, timeout=60) as r:
                    f.write(r.read())
            os.replace(tmp, dest)   # 원자적(부분 쓰기 시 .tmp 잔재만)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return dest

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
             parse_mode: str | None = None, disable_notification: bool = False) -> list[int]:
        """메시지 전송. 반환=모든 청크의 message_id 리스트 (pin 용=ids[-1]).
        reply_markup=키보드. parse_mode='Markdown'|'HTML'.
        disable_notification=True → 무음 전송.

        4096자 텔레그램 한도 초과 시 여러 통으로 분할. 분할된 경우 태그가 중간에
        잘려 깨지는 것을 피하려 parse_mode 는 포기하고 plain 으로 보낸다
        (포맷보다 전달 자체가 중요 — 2026-07-04 긴 회신이 통째로 유실된 사고 대응).

        모든 청크 message_id 반환 — reply_hook 이 각 청크를 같은 슬롯에 매핑
        (사용자가 첫 청크에 답장해도 라우팅 적중, 2026-07-06)."""
        if not chat_id:
            return []
        if len(text) <= MAX_TG_TEXT:
            data = {"chat_id": chat_id, "text": text,
                    "disable_notification": bool(disable_notification)}
            if parse_mode:
                data["parse_mode"] = parse_mode
            if reply_markup:
                data["reply_markup"] = reply_markup
            resp = self._api("sendMessage", data, timeout=10)
            mid = resp.get("result", {}).get("message_id")
            return [mid] if mid else []

        chunks = [text[i:i + MAX_TG_TEXT] for i in range(0, len(text), MAX_TG_TEXT)]
        ids: list[int] = []
        for i, chunk in enumerate(chunks):
            data = {"chat_id": chat_id, "text": chunk,
                    "disable_notification": bool(disable_notification)}
            if reply_markup and i == len(chunks) - 1:
                data["reply_markup"] = reply_markup
            resp = self._api("sendMessage", data, timeout=10)
            mid = resp.get("result", {}).get("message_id")
            if mid:
                ids.append(mid)
        return ids

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

    def get_my_commands(self, scope: dict | None = None) -> list:
        """현재 등록된 명령 메뉴 조회(getMyCommands). install 병합용.
        scope=None → default. 반환=[{command, description}, ...]."""
        payload: dict = {}
        if scope:
            payload["scope"] = scope
        resp = self._api("getMyCommands", payload, timeout=10)
        return resp.get("result", []) or []

    def _load_offset(self) -> int:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        """원자적 쓰기(임시파일+os.replace). write_text 직접 쓰기는 pm2 강제
        재시작 등으로 쓰기 도중 죽으면 파일이 손상돼 _load_offset 이 0으로
        폴백 → 이미 처리한 업데이트를 재수신(중복 주입) 할 수 있다."""
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.offset_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(offset))
            os.replace(tmp, self.offset_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
