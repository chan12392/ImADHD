"""/open 명령: 클로드 터미널 1개 새로 생성 (WT 신규 탭 + host.py PTY-bridge).

`wt -w new new-tab --title Claude cmd /c "cd <repo> && py -m imadhd.host -- claude"`
를 detached 로 spawn. host.py 가 bin/claude.exe 를 ConPTY 로 spawn 하고 자기
pid 를 자식 CC env 에 IMADHD_HOST_PID 로 주입 → register_hook 이 registry 에
host_pid 저장 → router 가 imadhd-stdin-<host_pid> 파이프로 주입(포커스 전환 0).

B-근본(2026-07-06): 파이프 이름 = host_pid(프로세스 고유). 이전 slot 기반
파이프(slot 3: 6회 0연결) 의 불일치/좀비 경쟁 회귀 해결.

CC 작업 cwd = 사용자 홈(Path.home()). host.py 모듈 해석은 repo(py -m)지만
CC 자체는 IMADHD_CC_CWD(=홈) 에서 시작 → CC 가 홈 기반 프로젝트
(`~/.claude/projects/C--Users-<name>/`) 로 인식 → resume 세션 목록에 기존
세션이 뜸. 대표님(user/chan1) 과 OSS 사용자 모두 동일 — 본인 홈이 곧 CC 의
자격증명/세션 기반 디렉터리.

/open 단일 명령(2026-07-06): 모델/provider 변형(/open glm, /open sonnet 등)
제거. 항상 기본 claude + 홈 cwd. 모델 변경은 CC 세션 안에서 직접.

claude = npm 글로벌(claude.cmd) → cmd /c 로 실행(.cmd 셸 필요).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .base import Command, Message, CommandContext, normalize_command

# imadhd 패키지 루트(repo). host.py 를 `-m imadhd.host` 로 실행하려면
# cwd 가 repo 여야(또는 패키지가 설치돼야) 모듈 해석이 된다.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])

_DETACHED = 0x08
_NEW_PROC_GROUP = 0x200

# /open 중복 spawn 가드(2026-07-07): 라우터가 409 Conflict(같은 봇 토큰 폴링 충돌)
# 로 동일 update 를 중복 처리하거나 대표님이 더블 탭할 때 tmux 세션이 1초 차로
# 2개 spawn 되는 현상 방지(Linux 실사고: 타임스탬프가 1초 차로 2개 spawn).
# 단일 라우터 프로세스 내 모듈 변수로 debounce.
_LAST_OPEN_MONO: float = 0.0
_OPEN_DEBOUNCE_SEC: float = 3.0

# z.ai(GLM) 프록시 전용 env 키. /open 단일화(Anthropic 공식 고정)로 항상 제거 —
# router(pm2) 가 옛 z.ai 셸 env 를 물려받아도 새 claude 는 로그인 계정으로 라우팅.
_ANTHROPIC_PROXY_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
)


def _wt_path() -> str:
    """wt.exe 경로. PATH → LOCALAPPDATA fallback(공개 툴 호환)."""
    import shutil
    return (
        shutil.which("wt.exe")
        or os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
                        "Microsoft", "WindowsApps", "wt.exe")
    )


def build_open_env(base_env: dict) -> dict:
    """새 claude 프로세스에 넘길 env 구성.

    - CC 작업 cwd = 홈(IMADHD_CC_CWD). host.py 가 이걸 읽어 CC spawn cwd 로 사용.
      목적: CC 가 홈 기반 프로젝트로 인식해 resume 세션 목록 노출.
    - CC identity env 오염 제거: router(pm2) 자체가 CC 터미널 안에서
      `pm2 start` 로 기동된 이력이 있으면 CLAUDECODE=1 /
      CLAUDE_CODE_SESSION_ID(고정된 옛 부모 세션) /
      CLAUDE_CODE_CHILD_SESSION=1 같은 "나는 CC의 nested child 세션이다"
      identity env 를 물려받아 새 claude 가 자기 transcript 를 디스크에 남기지
      않는다(2026-07-05 실사고: /open 터미널만 회신 안 감 — transcript .jsonl
      끝까지 생성 안 됨). AI_AGENT/CLAUDE* 전부 제거.
    """
    env = dict(base_env)
    env["IMADHD_CC_CWD"] = str(Path.home())
    for k in _ANTHROPIC_PROXY_ENV_KEYS:
        env.pop(k, None)
    for k in list(env):
        if k == "AI_AGENT" or k.startswith("CLAUDE"):
            env.pop(k, None)
    return env


def build_linux_launch_cmd() -> str:
    """Linux(tmux) 새 세션용 claude 실행 커맨드 문자열.

    보안:
    - --dangerously-skip-permissions는 기본 off. IMADHD_SKIP_PERMS=1 일 때만.
    - /open 단일화: 항상 기본 claude(홈 cwd). 모델/provider 인자 제거.
    """
    skip = " --dangerously-skip-permissions" if os.environ.get("IMADHD_SKIP_PERMS") == "1" else ""
    return (
        "bash -lc '"
        "export PATH=$HOME/.local/bin:$HOME/.bun/bin:$PATH; "
        "cd \"$HOME\" && exec claude" + skip +
        "'"
    )


class OpenCommand(Command):
    TRIGGERS = ("/open", "/새터미널", "/추가", "/new-term")

    def match(self, msg: Message) -> bool:
        # /open 단일만 매칭(/open glm 등 변형 제거). 인자 붙으면 미매치.
        return normalize_command(msg.text) in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        global _LAST_OPEN_MONO
        # debounce: 직전 /open 직후 짧은 시간 내 재진입(중복 update/더블 탭)은
        # 무시. 세션 2개 동시 spawn → registry 슬롯 2개 → 입력 분산/2번 작업 회피.
        now = time.monotonic()
        if now - _LAST_OPEN_MONO < _OPEN_DEBOUNCE_SEC:
            ctx.telegram.send(
                msg.chat_id,
                f"⏳ 직전 /open 직후 — 중복 생성 무시({_OPEN_DEBOUNCE_SEC:.0f}초 디바운스)",
            )
            return
        _LAST_OPEN_MONO = now
        if os.name == "nt":
            env = build_open_env(os.environ)
            # host 인자: [--] 뒤 child args 를 claude 에 그대로 전달.
            # cwd=repo(py -m 모듈 해석). CC 의 작업 cwd 는 IMADHD_CC_CWD(=홈).
            inner = f'cd /d "{_REPO_ROOT}" && py -m imadhd.host -- claude'
            try:
                subprocess.Popen(
                    [_wt_path(), "-w", "new", "new-tab", "--title", "Claude",
                     "cmd.exe", "/c", inner],
                    creationflags=_DETACHED | _NEW_PROC_GROUP,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    close_fds=True,
                    env=env,
                )
            except Exception as e:
                ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
                return
            ctx.telegram.send(
                msg.chat_id,
                f"🆕 새 터미널 생성 중… cwd={Path.home()} (수 초 내 번호 할당)",
            )
            return

        # 세션명 = prefix + 타임스탬프. 같은 초 더블 /open 은 handle 진입의
        # _OPEN_DEBOUNCE_SEC debounce 가 먼저 차단 → 세션명 충돌/2세션 spawn 없음.
        # prefix = IMADHD_TMUX_PREFIX(기본 'claude'). tmux_linux.py 폴백 타겟과 동일 변수.
        # 2026-07-08: 특정 배포 전용 세션명 하드코딩 → env 일반화. 기존
        # 세션명 유지하려면 IMADHD_TMUX_PREFIX=<이름> 설정.
        prefix = os.environ.get("IMADHD_TMUX_PREFIX", "claude")
        session_name = f"{prefix}-{int(time.time())}"
        launch_cmd = build_linux_launch_cmd()
        try:
            subprocess.run(["tmux", "new-session", "-d", "-s", session_name, launch_cmd],
                            timeout=10)
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
            return
        ctx.telegram.send(
            msg.chat_id, f"🆕 새 터미널 생성 중(tmux:{session_name})… (수 초 내 번호 할당)"
        )
