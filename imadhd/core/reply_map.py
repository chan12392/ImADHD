"""봇 송신 message_id → 터미널번호 매핑(JSONL append). 답장 라우팅용.

reply_hook(송신 측, Stop 훅)이 store, router(수신 측, pm2)가 lookup_num.
공유 파일 = data_dir/reply_map.jsonl.

설계: append-only JSONL. 단일 small write 는 POSIX/NT 에서 원자적 →
동시에 여러 터미널이 회신해도 줄 단위로 안전하게 쌓임(registry 의
read-modify-write 락 불필요). lookup 은 전 순회 후 최신값(TTL 내).

TTL 24h: 텔레그램 답장은 아주 오래된 메시지에도 가능하지만, 실사용에서
터미널 회신 후 24h 넘겨 답장할 일은 거의 없고 매핑 무한 증식 방지.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

TTL_SEC = 86400.0  # 24h
NAME = "reply_map.jsonl"


def _path(data_dir) -> Path:
    return Path(data_dir) / NAME


def store(data_dir, bot_msg_id: int, num: int) -> None:
    """봇 송신 message_id → 터미널번호 기록. append(원자적 small write).

    reply_hook 가 tg.send 반환값(message_id)과 info.number 로 호출.
    실패해도 회신 자체엔 영향 없음(조용히 무시) — 라우팅 편의 기능이므로.
    """
    if not bot_msg_id or not num:
        return
    try:
        p = _path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = json.dumps(
            {"msg_id": int(bot_msg_id), "num": int(num), "ts": time.time()},
            ensure_ascii=False,
        )
        with p.open("a", encoding="utf-8") as f:
            f.write(rec + "\n")
    except Exception:
        pass


def lookup_num(data_dir, bot_msg_id: int) -> int | None:
    """해당 봇 message_id 에 매핑된 최신 터미널번호. 만료/미존재 → None.

    router 가 인입 메시지의 reply_to_message.message_id 로 호출.
    같은 message_id 재사용(텔레그램 message_id 는 채팅 내에서 고유하므로 실제로
    희귀) 시 최신 레코드 우선. 파일 라인 수 = 24h 내 회신 수(수십~수백)라
    전 순회 비용 무시 가능.
    """
    if not bot_msg_id:
        return None
    p = _path(data_dir)
    if not p.exists():
        return None
    target = int(bot_msg_id)
    cutoff = time.time() - TTL_SEC
    latest: int | None = None
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("msg_id") != target:
                continue
            if rec.get("ts", 0) < cutoff:
                continue
            latest = rec.get("num")
    except Exception:
        return None
    return latest
