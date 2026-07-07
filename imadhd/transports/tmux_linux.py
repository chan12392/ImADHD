"""tmux 기반 입력 transport (Linux/오라클).

chleo-tg-poller.py(2026-07-03 LIVE 검증) 의 상태감지·주입 로직을 그대로
포팅. 핵심 교훈 2개:
  1. send-keys -l 은 한글 UTF-8 을 키 시퀀스로 보내 IME 조합 lock 유발 →
     반드시 load-buffer + paste-buffer 사용.
  2. CC 가 busy(응답 생성중) 일 때 주입하면 Enter 가 씹혀 텍스트만 잔류
     (stuck) → 주입 전 idle 대기 필수. C-c 는 CC 세션 자체를 죽이므로
     절대 사용 금지(입력 클리어는 idle 보장으로 사전 차단).

target(registry SessionInfo.to_dict())의 hwnd/pid 는 이 transport 에서
미사용(무의미) — target["tmux_pane"](세션별 tmux pane id)을 우선 쓰고,
없으면(구버전 슬롯) IMADHD_TMUX_TARGET 환경변수(기본 'chleo')로 폴백한다.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

from .base import InjectResult, Transport

TMUX_TARGET = os.environ.get("IMADHD_TMUX_TARGET", "chleo")


def _resolve_target(target: dict | None) -> str:
    """registry SessionInfo.to_dict() 에서 세션별 tmux_pane 우선 사용.
    없으면(구버전 슬롯/폴백 세션) 기존 고정 타겟으로 하위호환."""
    pane = (target or {}).get("tmux_pane") or ""
    return pane or TMUX_TARGET


# inject()가 idle-wait(최대 45s)+paste+Enter 를 라우터 메인루프에서 동기로
# 돌리면 그 동안 텔레그램 getUpdates 폴링 자체가 멈춰 다음 메시지를 못 읽고
# board(busy표시) 갱신도 밀린다(2026-07-05 실사고: "ping 보내고 답 없어서
# 다시 물으니 그제서야 pong 도착"). 실제 주입은 백그라운드 스레드로 넘기고
# 호출자(라우터 루프)는 즉시 반환받는다. 같은 pane 에 동시 두 스레드가
# paste-buffer 하면 텍스트가 섞이므로 lock 으로 직렬화.
_inject_lock = threading.Lock()

# CC 응답생성 스피너로 판정할 프롬프트 부재 최대 대기(초). 이 시간 넘게
# idle 이 안 되면 stuck 복구를 시도하되 계속 기다린다(호출자가 wait_idle 재호출).
_TMUX_CMD_TIMEOUT = 5


def _run(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, input=input_text, capture_output=True, text=True, timeout=_TMUX_CMD_TIMEOUT,
    )


def _has_session(target: str) -> bool:
    r = subprocess.run(["tmux", "has-session", "-t", target], capture_output=True)
    return r.returncode == 0


def _capture_pane(target: str, lines: int = 20) -> str | None:
    try:
        r = _run(["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"])
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _prompt_input_text(lines: list[str], prompt_idx: int) -> str:
    """❯ 프롬프트 줄 이후 실제 입력창에 남은 텍스트 추출(붙여넣은 텍스트가
    다음 줄로 렌더되는 CC 2.x 케이스 포함)."""
    parts = []
    first = lines[prompt_idx].strip().lstrip("❯").strip()
    if first:
        parts.append(first)
    for line in lines[prompt_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("❯") or s.startswith("─"):
            break
        if s.startswith("[") and s.endswith("]"):
            break
        if "bypass permissions" in s or "ctrl+" in s or "to edit" in s:
            break
        if s.startswith(("●", "✻", "✢", "✶", "✳", "✽")):
            break
        parts.append(s)
    return "\n".join(parts).strip()


def _state(target: str) -> str:
    """'idle' | 'busy' | 'stuck' | 'dead' | 'unknown'. idle 일 때만 주입 허용."""
    out = _capture_pane(target)
    if out is None:
        return "dead" if not _has_session(target) else "unknown"
    lines = out.splitlines()
    prompt_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("❯"):
            prompt_idx = i
            break
    if prompt_idx is None:
        return "busy"
    return "stuck" if _prompt_input_text(lines, prompt_idx) else "idle"


def _wait_idle(target: str, timeout: float = 45.0) -> str:
    """idle 될 때까지 대기. stuck(이전 주입 잔재) 은 Enter → (그래도 stuck)
    → C-j 순으로 복구 시도(chleo-tg-poller.py 원본 로직 — 이 포팅에서 Enter
    만 옮기고 C-j 폴백을 빠뜨렸던 버그를 2026-07-05 실사고로 발견해 복원.
    Enter 만으로 안 풀리는 stuck 이 실제로 있고, 그 상태로 영구 고착되면
    이후 모든 텔레그램 메시지가 이 pane 에 막혀 처리가 안 된다)."""
    deadline = time.time() + timeout
    rescued = False
    while time.time() < deadline:
        st = _state(target)
        if st in ("idle", "dead"):
            return st
        if st == "stuck" and not rescued:
            try:
                _run(["tmux", "send-keys", "-t", target, "Enter"])
            except Exception:
                pass
            time.sleep(1)
            if _state(target) == "stuck":
                try:
                    _run(["tmux", "send-keys", "-t", target, "C-j"])
                except Exception:
                    pass
                time.sleep(1)
            rescued = True
            continue
        time.sleep(1)
    return _state(target)


def _paste_inject(target: str, text: str) -> bool:
    """load-buffer+paste-buffer 로 주입 + Enter 제출(최대 3회 재시도).
    호출자가 idle 상태를 보장한 뒤에만 호출할 것."""
    clean = text.replace("\r", " ").replace("\n", " ")
    try:
        # paste 직전 idle 재확인: _wait_idle 이 idle 을 반환한 뒤에도 CC 가
        # 곧바로 busy(응답개시) 로 전환하는 race 가 있다. 그 구간에 paste 하면
        # 텍스트가 무시/잔류하므로 한 프레임 더 검증해 안정화한다.
        if _state(target) != "idle":
            return False
        rb = _run(["tmux", "load-buffer", "-"], input_text=clean)
        if rb.returncode != 0:
            return False
        _run(["tmux", "paste-buffer", "-t", target])
        time.sleep(0.2)
        if _state(target) != "stuck":
            return False  # 입력창에 안 들어감
        # 2026-07-07 실측(오라클 chleo stuck 사고): CC TUI 가 Enter(C-m) submit
        # 을 간헐적으로 무시하고 C-j(LF) 만 인식하는 케이스가 있다. _wait_idle
        # 에는 Enter→C-j 폴백이 있었으나 _paste_inject(실제 주입 경로)에는
        # Enter 3회만 있어 C-j 가 누락 → 텍스트 stuck → 응답 지연("한박자 늦음"
        # 근본원인). Enter 와 C-j 를 번갈아 4회 시도한다.
        for key in ("Enter", "C-j", "Enter", "C-j"):
            _run(["tmux", "send-keys", "-t", target, key])
            time.sleep(0.25)
            if _state(target) != "stuck":
                return True  # busy(제출성공) 또는 그 외 상태 전환
        return False  # 4회 시도해도 잔류
    except Exception:
        return False


def _inject_worker(tmux_target: str, text: str) -> None:
    with _inject_lock:
        st = _wait_idle(tmux_target, timeout=45.0)
        if st == "dead":
            return
        _paste_inject(tmux_target, text)


class TmuxLinuxTransport(Transport):
    def inject(self, target: dict, text: str, background: bool = False) -> InjectResult:
        tmux_target = _resolve_target(target)
        # dead 여부만 가볍게(동기) 확인 — 이 이상(_wait_idle 의 최대 45s
        # busy-polling)을 여기서 동기로 하면 2026-07-05 실사고("ping 보내고
        # 답 없어서 다시 물으니 그제서야 pong 도착")가 재발한다(라우터
        # 폴링 자체가 그동안 멈춤). idle 대기는 전부 워커 스레드 몫.
        if not _has_session(tmux_target):
            return InjectResult(delivered=False, method="tmux-paste", note="tmux session dead")
        threading.Thread(target=_inject_worker, args=(tmux_target, text), daemon=True).start()
        return InjectResult(delivered=True, method="tmux-paste-async", note="비동기 처리중")

    def is_alive(self, target: dict) -> bool:
        # has-session 만으로 판단한다. 예전엔 list-panes 로 pane_current_command
        # 에 "claude" 문자열이 있는지도 봤는데, CC 가 Bash 툴로 셸 명령을
        # 실행하는 동안은 그 pane 의 foreground 프로세스가 일시적으로
        # bash/python3/ssh 등으로 바뀐다 — 그때마다(하루 수십~수백 회) 이
        # 체크가 "dead" 오판을 냈고, 라우터 폴링 루프(5~6s 마다 sweep_dead
        # 호출)가 실제로 살아있는 클로이 세션의 registry 슬롯을 지워버렸다
        # (2026-07-05 실사고: "/open 빼고 전부 안 됨" — 슬롯이 계속
        # release 되니 숫자 라우팅이 전부 "터미널 없음"으로 실패).
        # tmux 세션 존재 여부만으로는 오판할 일이 없다(진짜 kill-session
        # 되기 전까진 계속 True).
        return _has_session(_resolve_target(target))
