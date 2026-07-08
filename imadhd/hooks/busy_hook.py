"""UserPromptSubmit 훅: CC가 사용자 입력을 받으면 즉시 busy(📝) 표시.

출처 게이트(2026-07-09): payload 의 prompt 에 reply_marker([A.D.H.D])가
있을 때만 busy — 텔레그램 인입(inject_command 가 마커 부착) 작업만 텔레그램에
"N번 작업중" 카운터로 표시. 데스크톱 앱/터미널 직접 타이핑(마커 없음)은
busy 안 됨 → progress_board/pin_board 에 안 뜸.

동작:
  - session_id 가 registry 에 등록된 슬롯이면 status="busy".
  - 미등록 슬롯이면 무시 (SessionStart 가 먼저 claim).
  - Stop 훅(reply_hook)이 마커 무관 status="idle" 로 복귀.

주의: 라우터 주입(텔레그램→CC) 경로에서도 UserPromptSubmit 발화 → 이미 busy 라
idempotent. stdout 출력 없음 (프롬프트 변형 금지).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _debug_log(line: str) -> None:
    """진단 로그(reply_hook 과 동일 포맷). busy_hook 은 실패 원인 추적이
    어려워 추가(2026-07-07 감사 P0 — 기존엔 진단 로그 전무)."""
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _prompt_has_marker(prompt: str, marker: str) -> bool:
    """UserPromptSubmit payload 의 prompt 에 reply_marker 가 있는지(=텔레그램 인입).
    마커 없으면 데스크톱 앱/터미널 직접 타이핑 → busy 안 됨 → 텔레그램 카운터 안 뜸."""
    return bool(marker) and marker in (prompt or "")


def _heal_session_drift(reg, data_dir, new_sid: str, cwd: str) -> bool:
    """/clear 직후 session_id 드리프트 자가치유.

    CC 는 /clear 를 같은 claude.exe PID 안에서 처리 → 새 transcript(새 session_id)
    를 시작하지만 SessionStart 훅은 프로세스 시작 1회만 발화 → registry 의
    session_id 가 갱신되지 않는다. 결과:
      - do_inject 가 marker_pending/<old_sid> 로 회신플래그 기록
      - reply_hook(Stop)이 new session_id 로 slot·marker 조회 실패 → 회신 스킵
    본 훅(UserPromptSubmit)이 new session_id 를 가장 먼저 관측 → 여기서 복구:
      1. 같은 cwd 슬롯 매칭(/clear 후에도 cwd 불변)
      2. claim_slot(pid 재사용 분기) 로 session_id 를 new 로 갱신
      3. marker_pending/<old> → /<new> 복사(직전 inject 의 회신플래그 보존)
    반환: 치유 성공 여부. 다중 CC 동일 cwd 등 모호하면 첫 매치(단일 CC 가정).
    """
    if not new_sid or not cwd:
        return False
    cand = None
    try:
        for it in reg.active():
            if (it.cwd or "") == cwd:
                cand = it
                break
    except Exception:
        return False
    if cand is None or (cand.session_id or "") == new_sid:
        return False
    old_sid = cand.session_id or ""
    try:
        # claim_slot 의 pid-재사용 분기가 같은 pid 슬롯을 찾아 session_id 갱신.
        # started_at·hwnd·pid·cwd 는 기존값 재전달(READY_GRACE·inject 경로 보존).
        reg.claim_slot(
            new_sid, cand.hwnd, cand.pid, cand.cwd, cand.started_at,
            tmux_pane=getattr(cand, "tmux_pane", ""),
        )
    except Exception as e:
        _debug_log(f"[busy] heal claim_slot failed old={old_sid[:8]} new={new_sid[:8]} err={e!r}")
        return False
    # marker 이전(old → new). /clear 직후 inject 가 old sid 로 남긴 회신플래그 보존.
    if old_sid and old_sid != new_sid and data_dir:
        try:
            d = Path(data_dir) / "marker_pending"
            old = d / old_sid
            if d.is_dir() and old.exists():
                (d / new_sid).write_text(old.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = payload.get("session_id", "") or ""
    if not session_id:
        return 0
    cwd = payload.get("cwd", "") or ""
    prompt = payload.get("prompt", "") or ""

    from ..config import Settings
    from ..core.registry import JSONFileRegistry

    # 설정 미구성/.env 깨짐 → 상태갱신만 스킵, 훅 자체는 죽지 않음.
    # UserPromptSubmit 훅이 죽으면 CC 입력 처리 자체가 불명확해진다
    # (reply_hook.py:276-280 동일 패턴 — 2026-07-07 감사 P0).
    try:
        s = Settings.load()
    except Exception as e:
        _debug_log(f"[busy] Settings.load failed session={session_id[:8]} err={e!r}")
        return 0

    # 출처 게이트: prompt 에 reply_marker 가 있어야 busy(텔레그램 인입).
    # 데스크톱 앱/터미널 직접 타이핑(마커 없음)은 busy 안 됨 → 텔레그램 카운터 안 뜸.
    # 단, /clear 드리프트 치유는 마커 무관(출처와 관계없이 발생) → 게이트 전에 수행.
    is_tg_inject = _prompt_has_marker(prompt, s.reply_marker)

    try:
        reg = JSONFileRegistry(s.registry_path, s.max_slots)
        if not reg.find_by_session(session_id):
            # /clear 등으로 같은 PID 에서 새 transcript(=새 session_id) 시작 시
            # SessionStart 훅이 재발화하지 않음 → registry 가 stale id 에 묶임 →
            # reply_hook(Stop)이 new id 로 slot·marker 조회 실패 → 회신 스킵
            # (=텔레그램 "전송 안 됨"). 같은 cwd 슬롯 session_id·marker 를 new 로 갱신.
            if _heal_session_drift(reg, s.data_dir, session_id, cwd):
                _debug_log(f"[busy] drift healed session={session_id[:8]} cwd={cwd!r}")
        if is_tg_inject and reg.find_by_session(session_id):
            reg.set_status_by_session(session_id, "busy")
        elif not is_tg_inject:
            _debug_log(
                f"[busy] no marker in prompt ({s.reply_marker}) — desktop direct, "
                f"skip busy session={session_id[:8]}"
            )
    except Exception as e:
        _debug_log(f"[busy] registry update failed session={session_id[:8]} err={e!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
