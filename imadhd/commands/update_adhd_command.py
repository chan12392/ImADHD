"""/update-adhd 명령: ImADHD 자체 갱신(git fetch → pull → pytest → pm2 restart).

restart 는 자기 자신(router)을 kill 하므로 **모든 답장은 restart 이전**.
분리 지연 서브프로세스(detach + 3s)로 답장 flush + 핸들러 정상 종료 시간 확보.
pytest 실패 시 restart 중단(끊긴 코드로 살아나는 사고 방지).

shell=True 문자열 호출 패턴(install.py/watchdog.py 동일) — npm global .CMD 경로
이슈·Windows 호환. 인자 고정상수라 injection 위험 0.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import Command, Message, CommandContext

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTEST_TIMEOUT = 300  # 초

# Windows 분리 플래그(비Windows 미존재 → hasattr 로 우회). open_command.py 패턴.
_CREATE_FLAGS = 0
if hasattr(subprocess, "DETACHED_PROCESS"):
    _CREATE_FLAGS |= subprocess.DETACHED_PROCESS
if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
    _CREATE_FLAGS |= subprocess.CREATE_NEW_PROCESS_GROUP


class UpdateAdhdCommand(Command):
    # 텔레그램 메뉴 command명은 밑줄(update_adhd, 규칙 ^[a-z0-9_]+$) 이라 /update_adhd 로
    # 도착. 대표님 자연 입력 /update-adhd(하이픈) 도 동일 매칭.
    TRIGGERS = {"/update-adhd", "/update_adhd", "/업데이트-adhd", "/업데이트_adhd"}

    def match(self, msg: Message) -> bool:
        return (msg.text or "").strip().lower() in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        tg = ctx.telegram
        chat = msg.chat_id
        tg.send(chat, "🔄 ImADHD 업데이트 중… (fetch → pull → pytest → restart)")

        # 1. fetch origin main (behind 판정 위해 최신 origin/main 필요)
        fetch = _run("git fetch origin main", timeout=60)
        if fetch.returncode != 0:
            tg.send(chat, f"❌ git fetch 실패:\n{_tail(fetch.stderr)}")
            return

        # 2. ahead/behind 확인 (사고2 교훈: pull 전 상태 점검). 출력="ahead\tbehind"
        rev = _run("git rev-list --left-right --count HEAD...origin/main", timeout=30)
        if rev.returncode != 0:
            tg.send(chat, f"❌ ahead/behind 확인 실패:\n{_tail(rev.stderr)}")
            return
        try:
            ahead_s, behind_s = rev.stdout.split()
            ahead, behind = int(ahead_s), int(behind_s)
        except Exception:
            tg.send(chat, f"❌ rev-list 파싱 실패:\n{rev.stdout!r}")
            return
        if behind == 0:
            tg.send(chat, f"✅ 이미 최신 (ahead={ahead}, behind=0)")
            return

        # 3. pull --ff-only (diverge/unrelated 시 실패 → 중단, 안전)
        pull = _run("git pull --ff-only origin main", timeout=120)
        if pull.returncode != 0:
            tg.send(chat, f"❌ git pull 실패(ff-only):\n{_tail(pull.stderr)}")
            return

        # 4. pytest smoke — 실패/timeout 시 restart 중단
        tg.send(chat, "🧪 pytest 실행 중…")
        try:
            pt = subprocess.run(
                "py -m pytest -q",
                shell=True, cwd=str(_REPO_ROOT),
                capture_output=True, text=True, timeout=_PYTEST_TIMEOUT,
            )
            pytest_ok = pt.returncode == 0
            tail = _tail(pt.stdout or pt.stderr)
        except subprocess.TimeoutExpired:
            tg.send(chat, f"❌ pytest timeout({_PYTEST_TIMEOUT}s) — restart 중단")
            return
        if not pytest_ok:
            tg.send(chat, "❌ pytest 실패 — restart 중단:\n" + tail)
            return

        # 5. restart (분리 지연) — 3초 뒤 pm2 restart. 답장은 이미 위에서 송신.
        # detach = 부모(router)가 3초 뒤 kill 되어도 자식 cmd 가 restart 완수.
        subprocess.Popen(
            "timeout /t 3 /nobreak >nul & pm2 restart imadhd",
            shell=True, cwd=str(_REPO_ROOT),
            creationflags=_CREATE_FLAGS,
            close_fds=True,
        )


def _run(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """git subprocess 래퍼. capture + text."""
    return subprocess.run(
        cmd, shell=True, cwd=str(_REPO_ROOT),
        capture_output=True, text=True, timeout=timeout,
    )


def _tail(s: str, n: int = 800) -> str:
    """출력 미리보기(텔레그램 답장용 길이 제한)."""
    if not s:
        return "(출력 없음)"
    s = s.strip()
    return s[-n:] if len(s) > n else s
