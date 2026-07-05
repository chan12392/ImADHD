"""고정 타겟(sticky) 영속: chat_id -> slot_num.

/use N 으로 설정한 고정 타겟을 data_dir/sticky.json 에 저장. router 가
시작 시 load, 변경 시 save. 단일 writer(router 프로세스)이므로 락 불필요 —
원자적 쓰기(tempfile + os.replace)로 프로세스 강제 종료에도 파일이
반쪽짜리로 남지 않음(registry._write 와 동일 패턴).

key=chat_id(str), value=slot_num(int). 빈 파일/결측 → {}.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

NAME = "sticky.json"


def _path(data_dir) -> Path:
    return Path(data_dir) / NAME


def load(data_dir) -> dict:
    """영속 파일에서 sticky dict 로드. 없거나 깨지면 빈 dict."""
    p = _path(data_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # 값은 int 로 정규화(잘못된 타입 섞임 방어)
    out: dict[str, int] = {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def save(data_dir, sticky: dict) -> None:
    """sticky dict 전체를 원자적 쓰기로 저장. router 단일 writer."""
    p = _path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {str(k): int(v) for k, v in sticky.items()}
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
