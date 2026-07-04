"""/open 명령: 클로드 터미널 1개 새로 생성 (WT 신규 창 + claude).

`wt -w new new-tab --title Claude cmd /c claude` 를 detached 로 spawn.
SessionStart 훅(btg-register)이 새 CC 세션을 잡아 자동 번호 할당 →
"✅ N번 연결됨" 알림이 이어서 옴(무음).

claude = npm 글로벌(claude.cmd) → cmd /c 로 실행(.cmd 셸 필요).

provider 선택: `/open` 기본은 Anthropic 공식(z.ai 프록시 env 제거),
`/open glm`(또는 z.ai/zai)은 상속받은 z.ai 프록시 env 그대로 유지.
router(pm2) 프로세스가 예전에 z.ai 모드였던 셸에서 뜬 채로 있으면
그 env(ANTHROPIC_BASE_URL 등)를 그대로 물려받아 "/open"만 해도 항상
z.ai로 뜨는 문제가 있었다(2026-07-04 발견) — 토큰은 코드에 넣지 않고
이미 상속된 env를 지우거나 유지하는 방식으로 전환한다.
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
    """새 claude 프로세스에 넘길 env 구성. use_glm=False 면 z.ai 프록시 키 제거."""
    env = dict(base_env)
    if not use_glm:
        for k in _ANTHROPIC_PROXY_ENV_KEYS:
            env.pop(k, None)
    return env


class OpenCommand(Command):
    TRIGGERS = ("/open", "/새터미널", "/추가", "/new-term")

    def match(self, msg: Message) -> bool:
        text = (msg.text or "").strip().lower()
        if text in self.TRIGGERS:
            return True
        parts = text.split(maxsplit=1)
        return len(parts) == 2 and parts[0] in self.TRIGGERS and parts[1] in _GLM_ALIASES

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        text = (msg.text or "").strip().lower()
        parts = text.split(maxsplit=1)
        use_glm = len(parts) == 2 and parts[1] in _GLM_ALIASES
        env = build_open_env(os.environ, use_glm)
        label = "GLM(z.ai)" if use_glm else "Anthropic 공식"
        try:
            subprocess.Popen(
                [_wt_path(), "-w", "new", "new-tab", "--title", "Claude",
                 "cmd.exe", "/c", "claude"],
                creationflags=_DETACHED | _NEW_PROC_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
                env=env,
            )
        except Exception as e:
            ctx.telegram.send(msg.chat_id, f"❌ 터미널 생성 실패: {e}")
            return
        ctx.telegram.send(msg.chat_id, f"🆕 새 터미널 생성 중({label})… (수 초 내 번호 할당)")
