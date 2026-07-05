"""imadhd install — 원라인 설치 (Windows + Linux).

4단계 전부 자동 + 멱등 + 백업:
  1. pm2 설치 + 재부팅 유지 (pm2-windows-startup + resurrect.cmd 절대경로 패치 + schtasks 이중화)
  2. 텔레그램 명령 메뉴 병합 (기존 사용자 명령 보존, ImADHD 와 충돌명만 교체)
  3. Claude Code 훅 자동 추가 (settings.json 멱등, 절대경로 python -m)
  4. 텔레그램 pin 최초 자동 생성 (빈 보드라도 즉시 고정)

사용:
  python -m imadhd install                      # 토큰/채팅: 프롬프트 또는 기존 .env
  python -m imadhd install --token X --chat 123
  python -m imadhd install --skip-pm2           # pm2 단계 건너뛰기 (이미 세팅됨)

토큰 소스 우선순위: --token 인자 > 환경변수 > 기존 .env > 인터랙티브 프롬프트.
토큰/채팅 은 repo/.env (router용, pm2 cwd=repo) + ~/.claude/settings.json env (CC 훅용)
양쪽에 주입 → config.py 수정 불필요.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---- 경로 ----
PKG_DIR = Path(__file__).resolve().parent          # imadhd/
REPO_DIR = PKG_DIR.parent                           # ImADHD/
ENV_FILE = REPO_DIR / ".env"
CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
PYTHON = sys.executable                             # install 실행 python (CC 훅도 이것 사용)


# ---- 로거 ----
def _step(msg: str) -> None:
    print(f"\n▶ {msg}")


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def _mask(token: str) -> str:
    return (token[:6] + "...") if token else "<empty>"


# ---- subprocess helper ----
def _run(cmd: str, check: bool = True, capture: bool = False):
    """문자열 명령 실행 (Windows shell). capture 시 CompletedProcess 반환."""
    r = subprocess.run(
        cmd, shell=True, capture_output=capture, text=True,
        encoding="utf-8", errors="replace",
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"명령 실패 (exit {r.returncode}): {cmd}\n"
            f"stdout: {r.stdout[-500:] if r.stdout else ''}\n"
            f"stderr: {r.stderr[-500:] if r.stderr else ''}"
        )
    return r


def _which(name: str) -> str | None:
    """PATH 에서 실행파일 찾기 (플랫폼 무관, shutil.which)."""
    return shutil.which(name)


# ---- 토큰/채팅 확정 ----
def resolve_credentials(args) -> tuple[str, str]:
    token = (args.token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (args.chat or os.environ.get("TELEGRAM_ALLOWED_CHAT_ID") or "").strip()
    # 기존 .env fallback
    if (not token or not chat) and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN=") and not token:
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TELEGRAM_ALLOWED_CHAT_ID=") and not chat:
                chat = line.split("=", 1)[1].strip().strip('"').strip("'")
    # 인터랙티브 프롬프트
    if not token and sys.stdin.isatty():
        token = input("Telegram bot token (@BotFather): ").strip()
    if not chat and sys.stdin.isatty():
        chat = input("본인 Telegram user id (@userinfobot): ").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 없음. --token 인자 또는 .env 세팅 필요.")
    if not chat:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID 없음. --chat 인자 필요 (공개 봇 보안).")
    return token, chat


def write_env(token: str, chat: str, max_slots: int) -> None:
    """repo/.env 작성 (router용). 기존 보존하며 키만 갱신."""
    _step(f".env 작성 → {ENV_FILE}")
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    kv = {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_ALLOWED_CHAT_ID": chat,
        "IMADHD_MAX_SLOTS": str(max_slots),
        "IMADHD_TRANSPORT": "sendkeys_win" if os.name == "nt" else "tmux_linux",
        "IMADHD_REPLY_MARKER": "[A.D.H.D]",
    }
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in kv:
            out.append(f"{key}={kv[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in kv.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    _ok(f"토큰 {_mask(token)} · 채팅 {chat} · 슬롯 {max_slots}")


# ============ Step 1: pm2 + 재부팅 유지 ============
def _npm_global_dir() -> Path:
    """npm global root (pm2-windows-startup 위치)."""
    r = _run("npm root -g", check=False, capture=True)
    p = (r.stdout or "").strip().splitlines()
    return Path(p[-1]) if p else Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"


def _patch_resurrect_cmd() -> bool:
    """pm2-windows-startup/pm2_resurrect.cmd 를 node 절대경로 직접 호출로 패치.
    PATH 의존 `pm2 resurrect` → 로그온 컨텍스트에서 조용히 실패하는 함정(재부팅 후 router 미부활) 수정.
    이미 절대경로면 미변경. 반환=변경여부."""
    node = _which("node") or r"C:\Program Files\nodejs\node.exe"
    pm2_bin = _npm_global_dir() / "pm2" / "bin" / "pm2"
    cmd_file = _npm_global_dir() / "pm2-windows-startup" / "pm2_resurrect.cmd"
    if not cmd_file.exists():
        return False
    body = cmd_file.read_text(encoding="utf-8", errors="replace")
    if "node.exe" in body and "resurrect" in body:
        return False  # 이미 패치됨
    patched = (
        "@echo off\r\n"
        f'rem patched by imadhd install (PATH-독립 node 절대경로 직접 호출) {datetime.date.today()}\r\n'
        f'"{node}" "{pm2_bin}" resurrect\r\n'
    )
    cmd_file.write_text(patched, encoding="utf-8")
    return True


def _pm2_has(name: str) -> bool:
    r = _run("pm2 jlist", check=False, capture=True)
    if r.returncode != 0 or not r.stdout:
        return False
    try:
        procs = json.loads(r.stdout)
        return any(p.get("name") == name for p in procs)
    except Exception:
        return False


def _register_schtask() -> bool:
    """schtasks ONLOGON 백업 등록 (HKCU Run 키와 이중화). 이미 있으면 -Force 갱신."""
    cmd_file = _npm_global_dir() / "pm2-windows-startup" / "pm2_resurrect.cmd"
    if not cmd_file.exists():
        return False
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"{cmd_file}\"';"
        "$t=New-ScheduledTaskTrigger -AtLogOn;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5);"
        "Register-ScheduledTask -TaskName 'imadhd-pm2-resurrect' -Action $a -Trigger $t "
        "-Settings $s -Force | Out-Null"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode == 0


def step1_pm2() -> None:
    """플랫폼 분기: Windows = pm2-windows-startup + schtasks 이중화, Linux = systemd."""
    if os.name == "nt":
        step1_pm2_windows()
    else:
        step1_pm2_linux()


def step1_pm2_linux() -> None:
    _step("Step 1 — pm2 설치 + 재부팅 유지 (Linux/systemd)")
    if not _which("node") or not _which("npm"):
        raise RuntimeError("Node.js/npm 없음. Node.js 설치 후 재실행 (예: apt install nodejs npm 또는 https://nodejs.org).")
    _ok("Node/npm 확인")
    if not _which("pm2"):
        _run("npm install -g pm2")
        _ok("pm2 설치")
    else:
        _ok("pm2 기존")
    # pm2 startup systemd — sudo 필요한 명령을 출력하므로 안내만 (자동실행은 사용자가 한 번)
    r = _run("pm2 startup systemd", check=False, capture=True)
    if r and r.returncode == 0 and r.stdout:
        _ok("pm2 systemd startup 안내 출력 — sudo 명령이 있으면 한 번 실행하여 부팅 시 자동복구 등록")
    else:
        _warn("pm2 startup systemd 자동실패 — 수동 `pm2 startup systemd` 실행 권장")
    # router 기동 (멱등)
    if _pm2_has("imadhd"):
        _ok("router 이미 online")
    else:
        _run(f'pm2 start "{PYTHON}" --name imadhd --cwd "{REPO_DIR}" -- -X utf8 -m imadhd.cli router')
        _ok("router 기동")
    _run("pm2 save")
    _ok("pm2 dump 저장 (재부팅 시 복원 대상)")


def step1_pm2_windows() -> None:
    _step("Step 1 — pm2 설치 + 재부팅 유지")
    if not _which("node") or not _which("npm"):
        raise RuntimeError("Node.js/npm 없음. https://nodejs.org 설치 후 재실행.")
    _ok("Node/npm 확인")
    # pm2 + pm2-windows-startup (없으면 설치)
    if not _which("pm2"):
        _run("npm install -g pm2")
        _ok("pm2 설치")
    else:
        _ok("pm2 기존")
    # pm2-windows-startup 존재 체크
    if not (_npm_global_dir() / "pm2-windows-startup").exists():
        _run("npm install -g pm2-windows-startup")
        _ok("pm2-windows-startup 설치")
    else:
        _ok("pm2-windows-startup 기존")
    # 부팅 자동시작 등록 (HKCU Run PM2 키)
    _run("pm2-startup install", check=False)
    _ok("HKCU Run PM2 키 등록 (로그온 시 resurrect)")
    # 함정 패치: resurrect.cmd 절대경로 node 화
    if _patch_resurrect_cmd():
        _ok("pm2_resurrect.cmd 절대경로 패치 (PATH 의존 함정 수정)")
    else:
        _ok("pm2_resurrect.cmd 이미 안전")
    # router 기동 (멱등)
    if _pm2_has("imadhd"):
        _ok("router 이미 online")
    else:
        _run(f'pm2 start "{PYTHON}" --name imadhd --cwd "{REPO_DIR}" -- -X utf8 -m imadhd.cli router')
        _ok("router 기동")
    _run("pm2 save")
    _ok("pm2 dump 저장 (재부팅 시 복원 대상)")
    # schtasks 이중화
    if _register_schtask():
        _ok("schtasks ONLOGON 백업 등록 (이중화)")
    else:
        _warn("schtasks 등록 실패 — HKCU Run 키만 의존 (로그에서 확인)")


# ============ Step 2: 텔레그램 명령 병합 ============
def _merge_commands(existing: list, ours: list) -> list:
    """기존 명령 보존, ImADHD 와 command 명 충돌 시 ImADHD 것으로 교체. 순서=ours 우선."""
    ours_names = {c["command"] for c in ours}
    kept = [c for c in existing if c.get("command") not in ours_names]
    # 중복 command 명 정규화 (Telegram 은 command 명 unique)
    seen = set()
    merged: list[str] = []
    for c in ours + kept:
        name = c.get("command")
        if not name or name in seen:
            continue
        seen.add(name)
        merged.append({"command": name, "description": c.get("description", "")})
    return merged


def step2_commands(token: str, chat: str, max_slots: int) -> None:
    _step("Step 2 — 텔레그램 명령 메뉴 (기존 보존 병합)")
    from .telegram_api.client import TelegramClient
    from .setup_commands import build_commands
    import tempfile
    off = Path(tempfile.gettempdir()) / "imadhd_install_offset.txt"
    tg = TelegramClient(token, off, None)
    ours = build_commands(max_slots)
    for label, scope in [("default", None), ("DM(private)", {"type": "all_private_chats"})]:
        try:
            existing = tg.get_my_commands(scope)
        except Exception as e:
            _warn(f"{label} 기존 명령 조회 실패 ({e}) — 덮어쓰기로 진행")
            existing = []
        merged = _merge_commands(existing, ours)
        try:
            tg.set_my_commands(merged, scope)
            kept = len(merged) - len(ours)
            _ok(f"{label}: ImADHD {len(ours)} + 기존 보존 {max(0, kept)} = {len(merged)} 명령")
        except Exception as e:
            _fail(f"{label} 등록 실패: {e}")
    # group/administrator 잔재 정리
    for sc in [{"type": "all_group_chats"}, {"type": "all_chat_administrators"}]:
        try:
            tg.delete_my_commands(sc)
        except Exception:
            pass


# ============ Step 3: Claude Code 훅 자동 추가 ============
# 직접 모듈 진입점 (cli 래퍼보다 의존 적음, 기존 수동 설치 훅과 동일 형태).
# (event, module, timeout, matcher or None)
HOOK_DEFS = [
    ("SessionStart", "imadhd.hooks.register_hook", 15000, None),
    ("Stop", "imadhd.hooks.reply_hook", 15000, None),
    ("PreToolUse", "imadhd.hooks.ask_hook", 300000, "AskUserQuestion"),
    ("UserPromptSubmit", "imadhd.hooks.busy_hook", 10000, None),
]


def _hook_command(module: str) -> str:
    return f'"{PYTHON}" -X utf8 -m {module}'


def _load_settings() -> dict:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            _warn(f"settings.json 파싱 실패 ({e}) — 백업 후 새 구조")
            backup = SETTINGS_FILE.with_suffix(f".json.bad-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
            SETTINGS_FILE.rename(backup)
    return {}


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def step3_hooks(token: str, chat: str) -> None:
    _step(f"Step 3 — Claude Code 훅 자동 추가 → {SETTINGS_FILE}")
    data = _load_settings()
    # 백업
    if SETTINGS_FILE.exists():
        bak = SETTINGS_FILE.with_suffix(f".json.bak-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(SETTINGS_FILE, bak)
        _ok(f"백업 → {bak.name}")
    # env 주입 (CC 훅이 토큰 읽는 소스)
    data.setdefault("env", {})
    data["env"]["TELEGRAM_BOT_TOKEN"] = token
    data["env"]["TELEGRAM_ALLOWED_CHAT_ID"] = chat
    hooks = data.setdefault("hooks", {})
    added = 0
    for event, module, timeout, matcher in HOOK_DEFS:
        group_list = hooks.setdefault(event, [])
        # 동일 모듈 이미 존재(경로 무관) → 멱등 스킵
        already = any(
            module in json.dumps(g, ensure_ascii=False)
            for g in group_list if isinstance(g, dict)
        )
        if already:
            _ok(f"{event}: 이미 등록됨 (스킵)")
            continue
        command = _hook_command(module)
        hook_obj = {"type": "command", "command": command, "timeout": timeout}
        entry: dict = {"hooks": [hook_obj]}
        if matcher:
            entry["matcher"] = matcher
        group_list.append(entry)
        added += 1
        _ok(f"{event}: 훅 추가" + (f" [matcher={matcher}]" if matcher else ""))
    _save_settings(data)
    _ok(f"총 {added}개 훅 추가 (기존 훅 전부 보존)")


# ============ Step 4: 텔레그램 pin 최초 자동 생성 ============
def step4_pin(token: str, chat: str, max_slots: int) -> None:
    _step("Step 4 — 텔레그램 pin 최초 자동 생성")
    try:
        from .core.registry import JSONFileRegistry
        from .telegram_api.client import TelegramClient
        from .boards.pin_board import PinBoard
    except Exception as e:
        _fail(f"모듈 import 실패 ({e}) — pin 생성 스킵. /pin 명령으로 수동 생성.")
        return
    data_dir = Path(os.environ.get("IMADHD_DATA_DIR", str(Path.home() / ".imadhd")))
    data_dir.mkdir(parents=True, exist_ok=True)
    off = data_dir / "offset.txt"
    tg = TelegramClient(token, off, chat)
    reg = JSONFileRegistry(data_dir / "registry.json", max_slots)
    board = PinBoard(tg, reg, chat, data_dir, max_slots)
    try:
        board.repin()  # 있으면 삭제후재생성, 없으면 create 동일
        _ok(f"핀 메시지 생성 + 고정 (status={board.status_id}, keyboard={board.keyboard_id})")
    except Exception as e:
        _fail(f"pin 생성 실패 ({e}) — router 기동 후 /pin 으로 수동 생성 가능")


# ============ diag ============
def diag() -> None:
    _step("진단 요약")
    # pm2
    if _pm2_has("imadhd"):
        _ok("router: online")
    else:
        _warn("router: 미기동 (수동 `pm2 restart imadhd` 필요)")
    # 훅
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            for ev in ("SessionStart", "Stop", "PreToolUse"):
                cnt = sum(
                    1 for g in hooks.get(ev, [])
                    if isinstance(g, dict) and "imadhd" in json.dumps(g, ensure_ascii=False)
                )
                _ok(f"훅 {ev}: imadhd {cnt}개")
        except Exception:
            _warn("settings.json 읽기 실패")
    _ok(f"python={PYTHON}")
    _ok("완료. Claude Code 세션을 새로 열면 SessionStart 가 슬롯 할당 + ✅ N번 연결됨 알림.")


# ============ main ============
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="imadhd install", description="ImADHD 원라인 설치")
    ap.add_argument("--token", help="Telegram bot token")
    ap.add_argument("--chat", help="본인 Telegram user id (allowed chat)")
    ap.add_argument("--max-slots", type=int, default=6)
    ap.add_argument("--skip-pm2", action="store_true", help="Step 1(pm2) 건너뛰기")
    ap.add_argument("--skip-pin", action="store_true", help="Step 4(pin) 건너뛰기")
    args = ap.parse_args(argv)

    print("=" * 60)
    print(" ImADHD installer — 원라인 (pm2 + 명령 + 훅 + pin)")
    print("=" * 60)

    token, chat = resolve_credentials(args)
    write_env(token, chat, args.max_slots)

    if args.skip_pm2:
        _warn("Step 1 건너뜀 (--skip-pm2)")
    else:
        step1_pm2()
    step2_commands(token, chat, args.max_slots)
    step3_hooks(token, chat)
    if not args.skip_pin:
        step4_pin(token, chat, args.max_slots)
    diag()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _warn("사용자 중단")
        sys.exit(130)
    except Exception as e:
        _fail(f"설치 중단: {e}")
        sys.exit(1)
