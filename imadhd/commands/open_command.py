"""/open 명령: 클로드 터미널 1개 새로 생성 (WT 신규 창 + claude).

`wt -w new new-tab --title Claude cmd /c claude` 를 detached 로 spawn.
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
import shutil
import subprocess

from .base import Command, Message, CommandContext

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
    GLM 별칭이면 (True, None). 그 외는 모델명으로 간주해 (False, arg)."""
    if not arg:
        return False, None
    if arg in _GLM_ALIASES:
        return True, None
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
        use_glm, model = parse_open_arg(arg)

        env = build_open_env(os.environ, use_glm)
        claude_cmd = ["claude"] if not model else ["claude", "--model", model]
        if use_glm:
            label = "GLM(z.ai)"
        elif model:
            label = f"Anthropic 공식 · {model}"
        else:
            label = "Anthropic 공식"

        try:
            subprocess.Popen(
                [_wt_path(), "-w", "new", "new-tab", "--title", "Claude",
                 "cmd.exe", "/c"] + claude_cmd,
                creationflags=_DETACHED | _NEW_PROC_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
                env=env,
            )
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
            return
        ctx.telegram.send(msg.chat_id, f"🆕 새 터미널 생성 중({label})… (수 초 내 번호 할당)")
