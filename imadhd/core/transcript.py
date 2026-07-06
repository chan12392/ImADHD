"""CC transcript JSONL 에서 ai-title(세션 한 줄 요약) 읽기.

CC 가 현재 모델로 자동 생성하는 세션 제목. /list '탭 이름' 표시용.
WT 비활성 탭 이름은 Win32 API 로 못 얻어 ai-title 이 가장 가까운 자동값.

레코드 형식(2026-07-07 실측):
  {"type":"ai-title", "aiTitle":"<한 줄 요약>", "sessionId":"<uuid>"}
필드명 = aiTitle(title 아님). 한글 OK. 세션 갱신마다 여러 번 기록 → 마지막이 최신.

경로 탐색(2026-07-07 실측):
  registry.cwd = /open 호출 repo 경로. but CC 실제 transcript cwd = home
  (host.py 가 home 에서 spawn). 불일치 → cwd 기반 경로 계산 안 됨.
  → session_id 로 폴더 무관 glob. session_id 유일 → 정확 매칭.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def encode_cwd(cwd: str) -> str:
    """CC transcript 폴더명 인코딩: non-alphanumeric → '-'.
    실측: C:\\Users\\chan1 → C--Users-chan1 (':'·'\\' 각각 '-'). 참고용(cwd 불일치로 미사용)."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def find_transcript(
    session_id: str, claude_home: Optional[Path] = None
) -> Optional[Path]:
    """session_id 로 transcript 파일 찾기. 폴더 무관 glob.

    projects/<any-folder>/<session_id>.jsonl. session_id 유일성으로 cwd 불일치
    (registry.cwd vs CC 실제 home cwd) 무관하게 정확 매칭.
    claude_home 기본 = Path.home()/.claude(주입 가능 — 테스트용)."""
    if not session_id:
        return None
    base = claude_home if claude_home is not None else Path.home() / ".claude"
    projects = base / "projects"
    if not projects.exists():
        return None
    matches = list(projects.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


def read_ai_title(
    session_id: str, cwd: str = "", claude_home: Optional[Path] = None
) -> str:
    """세션의 최신 ai-title 반환. 없음/에러시 ''.

    cwd 인자는 호환용(무시) — find_transcript 가 session_id 폴더 무관 탐색.
    파일 전체 순회 후 마지막 ai-title 사용(세션 진행中 갱신 시 최신값).
    ai-title 없음 = 아직 첫 응답 전(세션 시작 직후) → 호출측에서 HH:MM 폴백."""
    p = find_transcript(session_id, claude_home)
    if p is None or not p.exists():
        return ""
    title = ""
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") == "ai-title":
                    t = o.get("aiTitle") or ""
                    if t:
                        title = str(t)
    except Exception:
        return ""
    # 60자 절단(텔레그램 한 줄 가독). 한글 60자 = 충분히 요약.
    return title[:60]

