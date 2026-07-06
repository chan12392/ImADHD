"""/open 명령: 클로드 터미널 1개 새로 생성 (WT 신규 창 + claude).

`wt -w new new-tab --title Claude cmd /c "cd <repo> && py -m imadhd.host -- claude"`
를 detached 로 spawn. host.py 가 ConPTY 위에서 claude 를 spawn 하고
세션별 named-pipe 서버(\\.\pipe\imadhd-slot-<N>)를 띄운다 → 라우터가
포커스 강제 전환 없이 텔레그램 입력을 주입할 수 있다.
SessionStart 훅(btg-register)이 새 CC 세션을 잡아 자동 번호 할당 →
"✅ N번 연결됨" 알림이 이어서 옴(무음).

claude = npm 글로벌(claude.cmd) → cmd /c 로 실행(.cmd 셸 필요).

provider/모델 선택: `/open` 기본은 Anthropic 공식(z.ai 프록시 env 제거) +
CC 기본 모델. `/open glm`(또는 z.ai/zai)은 상속받은 z.ai 프록시 env 그대로
유지. 그 외 인자(`/open opus`, `/open sonnet-4-5` 등)는 Anthropic 공식 +
`claude --model <인자>` 로 그 모델 지정 실행. 숫자 하나짜리 인자(`/open 1`)는
슬롯 선택 등 다른 명령과 헷갈릴 수 있어 제외.

router(pm2) 프로세스가 예전에 z.ai 모드였던 셸에서 뜬 채로 있으면 그
env(ANTHROPIC_BASE_URL 등)를 그대로 물려받아 "/open"만 해도 항상 z.ai로
뜨는 문제가 있었다(2026-07-04 발견) — 토큰은 코드에 넣지 않고 이미
상속된 env를 지우거나 유지하는 방식으로 전환한다.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .base import Command, Message, CommandContext

# imadhd 패키지 루트(repo). host.py 를 `-m imadhd.host` 로 실행하려면
# cwd 가 repo 여야(또는 패키지가 설치돼야) 모듈 해석이 된다.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])

_DETACHED = 0x08
_NEW_PROC_GROUP = 0x200

# z.ai(GLM) 프록시 전용 env 키. 공식 Anthropic 모드에선 이걸 지워야
# 로그인된 계정(~/.claude 자격증명)으로 정상 라우팅된다.
_ANTHROPIC_PROXY_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
)
_GLM_ALIASES = ("glm", "z.ai", "zai")

# 모델명은 안전한 문자클래스만 허용. 셸 메타/치환(`$`, `;`, `|`, backtick, 공백 등) 차단.
_MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def build_linux_launch_cmd(use_glm: bool, model: str | None) -> str:
    """오라클(tmux) 새 세션용 claude 실행 커맨드 문자열 조립 (안전 버전).

    보안:
    - GLM 토큰은 bash export 문(커맨드라인/ps/로그 노출)이 아니라
      0600 권한의 ~/.anthropic.env 파일을 source 하는 방식으로만 주입.
    - --dangerously-skip-permissions는 기본 off. IMADHD_SKIP_PERMS=1 일 때만.
    - model 인자는 _MODEL_RE 로 사전 검증 + shlex.quote 이중 방어.
    """
    parts = ["bash -lc '"]
    parts.append("export PATH=$HOME/.local/bin:$HOME/.bun/bin:$PATH; ")
    if use_glm:
        parts.append("source $HOME/.anthropic.env 2>/dev/null || true; ")
    parts.append("cd /home/ubuntu && exec claude")
    if os.environ.get("IMADHD_SKIP_PERMS") == "1":
        parts.append(" --dangerously-skip-permissions")
    if model:
        parts.append(f" --model {shlex.quote(model)}")
    parts.append("'")
    return "".join(parts)


def _wt_path() -> str:
    """wt.exe 경로. PATH → LOCALAPPDATA fallback(공개 툴 호환)."""
    return (
        shutil.which("wt.exe")
        or os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
                        "Microsoft", "WindowsApps", "wt.exe")
    )


def build_open_env(base_env: dict, use_glm: bool) -> dict:
    """새 claude 프로세스에 넘길 env 구성. use_glm=False 면 z.ai 프록시 키 제거.

    router(pm2) 자체가 CC 터미널 안에서 `pm2 start` 로 기동된 이력이 있어
    CLAUDECODE=1 / CLAUDE_CODE_SESSION_ID(고정된 옛 부모 세션) /
    CLAUDE_CODE_CHILD_SESSION=1 같은 "나는 CC의 nested child 세션이다"
    identity env 를 그대로 물려받는다. 이걸 새로 띄우는 claude 프로세스에
    그대로 넘기면 그 프로세스가 옛 고정 세션의 자식으로 오인해 자기
    transcript 를 정상적으로 디스크에 남기지 않는다(2026-07-05 실사고:
    /open 으로 연 터미널만 텔레그램 회신 안 감 — transcript .jsonl 자체가
    끝까지 생성 안 됨. 수동으로 연 터미널은 이 env 오염이 없어 정상)."""
    env = dict(base_env)
    if not use_glm:
        for k in _ANTHROPIC_PROXY_ENV_KEYS:
            env.pop(k, None)
    for k in list(env):
        if k == "AI_AGENT" or k.startswith("CLAUDE"):
            env.pop(k, None)
    return env


def parse_open_arg(arg: str) -> tuple[bool, str | None]:
    """/open 뒤 인자 → (use_glm, model). arg 없으면 (False, None).
    GLM 별칭이면 (True, None). 그 외는 모델명으로 간주해 (False, arg).
    모델명은 _MODEL_RE(안전 문자클래스) 통과해야 함 — 셸 인젝션 차단."""
    if not arg:
        return False, None
    if arg in _GLM_ALIASES:
        return True, None
    if not _MODEL_RE.match(arg):
        raise ValueError(f"unsafe model arg: {arg!r}")
    return False, arg


class OpenCommand(Command):
    TRIGGERS = ("/open", "/새터미널", "/추가", "/new-term")

    def match(self, msg: Message) -> bool:
        text = (msg.text or "").strip().lower()
        if text in self.TRIGGERS:
            return True
        parts = text.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in self.TRIGGERS:
            return False
        arg = parts[1].strip()
        # 순수 숫자(예: /open 1)는 슬롯 선택 등 다른 명령과 헷갈릴 수 있어 제외.
        return bool(arg) and not arg.isdigit()

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        text = (msg.text or "").strip().lower()
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) == 2 else ""
        try:
            use_glm, model = parse_open_arg(arg)
        except ValueError:
            ctx.telegram.send(
                msg.chat_id,
                "❌ 모델명에 허용되지 않는 문자가 있습니다 (A-Z a-z 0-9 . _ - 만 가능).",
            )
            return

        if use_glm:
            label = "GLM(z.ai)"
        elif model:
            label = f"Anthropic 공식 · {model}"
        else:
            label = "Anthropic 공식"

        if os.name == "nt":
            env = build_open_env(os.environ, use_glm)
            claude_cmd = ["claude"] if not model else ["claude", "--model", model]
            # WT 탭에서 claude 를 직접 실행(수동 터미널과 동등). host.py(winpty PTY
            # + named-pipe 서버) 래핑은 한때 pipe 기반 백그라운드(포커스 무점유) 주입
            # 용이었으나, 현재 transport=sendkeys(포커스 주입)라 파이프 서버를 쓰지
            # 않는다. host.py 경로는 npm shim(cmd /c claude.cmd)이 node(claude.exe)
            # 를 띄운 뒤 즉시 exit → winpty PTY 자식 사망 → host.py 종료(code 1) →
            # claude.exe 가 TTY 없이 고아화돼 transcript 도 안 쓰고 입력도 처리 못
            # 하는 버그가 있어 제거(2026-07-06 실측). 직접 실행 시 WT 탭이 진짜 TTY
            # 를 제공하므로 수동 터미널과 동일하게 동작(sync_alive 가 등록, sendkeys
            # 가 주입, transcript 정상 작성 → 회신 경로까지 정상).
            inner = f'cd /d "{_REPO_ROOT}" && ' + subprocess.list2cmdline(claude_cmd)
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
            ctx.telegram.send(msg.chat_id, f"🆕 새 터미널 생성 중({label})… (수 초 내 번호 할당)")
            return

        session_name = f"chleo-{int(time.time())}"
        launch_cmd = build_linux_launch_cmd(use_glm, model)
        try:
            subprocess.run(["tmux", "new-session", "-d", "-s", session_name, launch_cmd],
                            timeout=10)
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
            return
        ctx.telegram.send(
            msg.chat_id, f"🆕 새 터미널 생성 중({label}, tmux:{session_name})… (수 초 내 번호 할당)"
        )
