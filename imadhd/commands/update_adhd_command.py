"""/update-adhd 명령: ImADHD 자체 갱신.

2단계(대표님 2026-07-07):
  1. handle(): fetch → behind 판정 → 버전(local/remote) + CHANGELOG 최신 섹션 +
     인라인 Yes/No 팝업. behind==0 → "최신" 종료.
  2. 콜백 yes → run_update(): pull --ff-only → pytest → 3초 분리 pm2 restart.

restart 는 자기 자신(router)을 kill 하므로 **run_update 답장은 restart 이전**.
분리 지연 서브프로세스(detach + 3s)로 답장 flush + 핸들러 종료 시간 확보.
pytest 실패 시 restart 중단(끊긴 코드로 살아나는 사고 방지).

버전 소스 = CHANGELOG.md(pyproject 0.1.0 stale 이슈로 신뢰 불가). 로컬 vs
origin/main 첫 '## X.Y.Z' 비교. behind 카운트로 실제 갱신 유무 판정.

shell=True 문자열 호출(install.py/watchdog.py 동일) — npm global .CMD 경로
이슈·Windows 호환. 인자 고정상수라 injection 위험 0.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .base import Command, Message, CommandContext, normalize_command

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTEST_TIMEOUT = 300  # 초

# Windows 분리 플래그(비Windows 미존재 → hasattr 로 우회). open_command.py 패턴.
_CREATE_FLAGS = 0
if hasattr(subprocess, "DETACHED_PROCESS"):
    _CREATE_FLAGS |= subprocess.DETACHED_PROCESS
if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
    _CREATE_FLAGS |= subprocess.CREATE_NEW_PROCESS_GROUP

# CHANGELOG 버전 헤더: '## 0.3.2 — 2026-07-05' 등.
_VERSION_RE = re.compile(r"^##\s+(\d+\.\d+\.\d+)", re.MULTILINE)


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


def _first_version(text: str) -> str:
    """CHANGELOG 본문에서 첫 '## X.Y.Z' 버전 추출. 없으면 '?'."""
    m = _VERSION_RE.search(text or "")
    return m.group(1) if m else "?"


def _local_changelog() -> str:
    try:
        return (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except Exception:
        return ""


def _remote_changelog() -> str:
    """origin/main 의 CHANGELOG.md. fetch 후 호출 전제."""
    r = _run("git show origin/main:CHANGELOG.md", timeout=30)
    return r.stdout if r.returncode == 0 else ""


def _latest_section(text: str, ver: str) -> str:
    """'## <ver>' 헤더부터 다음 '## ' 전까지 발췌. ver 못 찾으면 첫 섹션."""
    lines = (text or "").splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## ") and ver != "?" and ver in ln:
            start = i
            break
    if start is None:
        for i, ln in enumerate(lines):
            if ln.strip().startswith("## "):
                start = i
                break
    if start is None:
        return "(내역 없음)"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).strip() or "(내역 없음)"


def run_update(tg, chat: str) -> None:
    """콜백 Yes → 실제 갱신: pull --ff-only → pytest → 분리 restart.

    handle() 본문에서 분리(콜백 양쪽 재사용). restart 전 답장 송신.
    """
    pull = _run("git pull --ff-only origin main", timeout=120)
    if pull.returncode != 0:
        tg.send(chat, f"❌ git pull 실패(ff-only):\n{_tail(pull.stderr)}")
        return
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
    tg.send(chat, "✅ pytest 통과. 3초 후 restart…")
    # detach = 부모(router)가 3초 뒤 kill 되어도 자식 cmd 가 restart 완수.
    subprocess.Popen(
        "timeout /t 3 /nobreak >nul & pm2 restart imadhd",
        shell=True, cwd=str(_REPO_ROOT),
        creationflags=_CREATE_FLAGS,
        close_fds=True,
    )


class UpdateAdhdCommand(Command):
    # 텔레그램 메뉴 command명은 밑줄(update_adhd, 규칙 ^[a-z0-9_]+$) 이라 /update_adhd 로
    # 도착. 대표님 자연 입력 /update-adhd(하이픈) 도 동일 매칭.
    TRIGGERS = {"/update-adhd", "/update_adhd", "/업데이트-adhd", "/업데이트_adhd"}

    def match(self, msg: Message) -> bool:
        return normalize_command(msg.text) in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        tg = ctx.telegram
        chat = msg.chat_id
        tg.send(chat, "🔄 업데이트 확인 중… (fetch origin/main)")

        # 1. fetch (behind 판정·remote CHANGELOG 위해 최신 origin/main 필요)
        fetch = _run("git fetch origin main", timeout=60)
        if fetch.returncode != 0:
            tg.send(chat, f"❌ git fetch 실패:\n{_tail(fetch.stderr)}")
            return

        # 2. ahead/behind (출력="ahead\tbehind")
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

        # 3. 버전 + CHANGELOG 최신 섹션
        local_ver = _first_version(_local_changelog())
        remote_text = _remote_changelog()
        remote_ver = _first_version(remote_text)

        if behind == 0:
            tg.send(chat, f"✅ 이미 최신 (v{local_ver}, ahead={ahead})")
            return

        section = _latest_section(remote_text, remote_ver)
        text = (
            f"📦 버전: v{local_ver} → v{remote_ver}\n"
            f"(behind={behind}, ahead={ahead})\n"
            f"\n📝 업데이트 내역:\n{section[:1200]}\n"
            f"\n업데이트 하시겠습니까?"
        )
        kb = [
            [
                {"text": "✅ 예", "callback_data": "u:update:yes"},
                {"text": "❌ 아니오", "callback_data": "u:update:no"},
            ]
        ]
        tg.send(chat, text, reply_markup={"inline_keyboard": kb})
