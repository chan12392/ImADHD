"""router 좀비 감시(pm2 데몬, imadhd-watchdog).

2026-07-05 실사고: pm2 가 imadhd 를 status=online/pid=N/A 로 표시하는데
실제 python 프로세스는 없는 좀비 상태로 남아 14분+ 방치됨(heartbeat.txt
정지, offset.txt 정지, 텔레그램 pending_update_count 누적). pm2 자체
헬스체크로는 이 상태를 못 잡는다(온라인이라고 믿음) — heartbeat.txt
신선도로 별도 감시해 stale 이면 `pm2 restart imadhd` 로 자가복구.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

# router 루프는 통상 <10s 주기로 heartbeat 갱신(long-poll timeout=5s +
# sweep/board 처리). 60s 여유를 둬 일시적 지연 오탐 방지.
STALE_THRESHOLD_SEC = 60.0
CHECK_INTERVAL_SEC = 20.0


def _debug_log(line: str) -> None:
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _heartbeat_age(heartbeat_path: Path) -> float | None:
    try:
        ts = float(heartbeat_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return time.time() - ts


def watchdog_main() -> int:
    from .config import Settings

    s = Settings.load()
    hb = s.heartbeat_path
    _debug_log(f"[watchdog] start threshold={STALE_THRESHOLD_SEC}s interval={CHECK_INTERVAL_SEC}s")
    last_restart = 0.0
    while True:
        time.sleep(CHECK_INTERVAL_SEC)
        age = _heartbeat_age(hb)
        if age is None:
            # heartbeat 파일 자체가 없음 = router 최초 기동 전(정상, 넘어감).
            continue
        if age <= STALE_THRESHOLD_SEC:
            continue
        # 재시작 직후 router 가 첫 heartbeat 를 쓰기까지 걸리는 시간을
        # 감안해 연속 재시작 폭주 방지(최소 간격).
        if time.time() - last_restart < STALE_THRESHOLD_SEC:
            continue
        _debug_log(f"[watchdog] heartbeat stale age={age:.1f}s → pm2 restart imadhd")
        try:
            # Windows 에서 npm global pm2 = pm2.CMD shim. shell=False 리스트 호출은
            # PATH 의 .CMD 를 못 찾아 FileNotFoundError → restart 무력(2026-07-06 실측).
            # 인자 고정이라 shell=True 문자열로 안전. boot_check 와 동일 패턴.
            subprocess.run("pm2 restart imadhd", shell=True, check=False,
                            capture_output=True, timeout=30)
        except Exception as e:
            _debug_log(f"[watchdog] pm2 restart failed: {e!r}")
        last_restart = time.time()


if __name__ == "__main__":
    raise SystemExit(watchdog_main())
