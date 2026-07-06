"""부팅/resurrect 직후 pm2 좀비(online/pid=N/A) 자가복구 — 1차 방어.

2026-07-06 재사고: 재부팅 후 pm2-windows-startup 의 pm2_resurrect.cmd 가
`pm2 resurrect` 를 실행하면 dump 에서 imadhd + imadhd-watchdog 이
status=online/pid=N/A/mem=0b 좀비로 복원됨(Windows fork 모드 pm2 알려진 동작).
실제 python 프로세스는 없는데 pm2 는 online 이라 믿음.

watchdog.py(2차 방어)는 heartbeat 신선도로 imadhd 만 감시하며, watchdog 자신은
좀비가 되면 스스로 못 살린다. 그래서 부팅 시점에 watchdog 까지 확실히 깨우는
1차 방어가 별도로 필요하다.

cmd 파일(pm2_resurrect.cmd)이 `pm2 resurrect` 직후 이 모듈을 호출:
    python -X utf8 -m imadhd.boot_check
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

# 부팅 시 확실히 살려야 할 대상. watchdog 포함 — 1차가 못 깨우면 2차 무의미.
TARGETS = ("imadhd", "imadhd-watchdog")

# resurrect 직후 pm2 db 갱신 대기 + 재시도 폭주 방지.
MAX_ATTEMPTS = 3
RESTART_RETRY_INTERVAL_SEC = 3.0


def _debug_log(line: str) -> None:
    """watchdog.py 의 _debug_log 와 같은 경로(~/.imadhd/debug.log)."""
    try:
        p = Path.home() / ".imadhd" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _pm2_jlist() -> list:
    """`pm2 jlist` 파싱. 실패 시 빈 리스트(안전 폴백).

    Windows 에선 npm global `pm2` 가 `pm2.CMD` shim 이라 shell=False 리스트 호출로는
    PATH 탐색이 안 됨(FileNotFoundError) → install.py _run 과 동일하게 shell=True
    문자열 사용. 인자는 고정(jlist)이라 injection 면.
    """
    try:
        r = subprocess.run(
            "pm2 jlist", shell=True, capture_output=True, text=True, timeout=30
        )
    except Exception as e:
        _debug_log(f"[boot_check] pm2 jlist failed: {e!r}")
        return []
    if r.returncode != 0 or not r.stdout:
        return []
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        _debug_log(f"[boot_check] pm2 jlist parse failed: {e!r}")
        return []


def is_zombie(proc: dict) -> bool:
    """online 인데 pid 가 없는(None/0) 좀비 여부.

    pm2 list 에서 pid=N/A 로 표시되는 이번 사고의 정확한 패턴.
    psutil 의존 없이 pid falsy 만으로 판정한다.
    """
    if proc.get("name") not in TARGETS:
        return False
    env = proc.get("pm2_env") or {}
    if env.get("status") != "online":
        return False
    return not proc.get("pid")  # None / 0 → 좀비


def boot_check() -> int:
    """좀비 대상을 pm2 restart 로 깨움. 정상화=0, 잔존=1."""
    _debug_log("[boot_check] start")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        procs = _pm2_jlist()
        targets = [p["name"] for p in procs if is_zombie(p)]
        if not targets:
            _debug_log(f"[boot_check] no zombies (attempt {attempt})")
            return 0
        # 중복 제거(imadhd, imadhd-watchdog 순서 보존)
        seen: list[str] = []
        for n in targets:
            if n not in seen:
                seen.append(n)
        _debug_log(
            f"[boot_check] zombies={seen} attempt={attempt} → pm2 restart"
        )
        try:
            # seen 은 TARGETS 고정 상수만 → injection 면. Windows pm2.CMD shim 호환.
            subprocess.run(
                f'pm2 restart {" ".join(seen)}',
                shell=True, capture_output=True, timeout=30,
            )
        except Exception as e:
            _debug_log(f"[boot_check] pm2 restart failed: {e!r}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(RESTART_RETRY_INTERVAL_SEC)
    # 최종 재확인
    procs = _pm2_jlist()
    if not any(is_zombie(p) for p in procs):
        _debug_log("[boot_check] recovered after retries")
        return 0
    _debug_log("[boot_check] zombies still present after max attempts")
    return 1


if __name__ == "__main__":
    raise SystemExit(boot_check())
