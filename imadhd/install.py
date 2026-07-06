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
토큰/채팅 은 repo/.env (router용, pm2 cwd=repo) + ~/.imadhd/env (CC 훅용, 0600)
양쪽에 주입. settings.json global env 는 쓰지 않음 → CC 세션/하위 프로세스 토큰
확산 차단. step3_hooks() 는 기존 설치가 global env 에 남긴 토큰을 제거(마이그레이션).
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


def _restrict_perms(path: Path) -> None:
    """파일 권한 0600 (Linux/macOS). Windows umask 무의미 → no-op."""
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _write_secret(path: Path, content: str) -> None:
    """0600 파일 갱신(POSIX umask/loose-perm TOCTOU 방지).

    두 가지 창을 막는다:
    1. 신규 생성 — os.open(..., 0o600) 이 fd 생성 단계부터 모드 고정.
    2. 기존 파일이 0644 였던 경우 — O_CREAT|O_TRUNC 는 mode 인자를 무시하고
       기존 모드를 유지하므로, fdopen/write 전 os.fchmod(fd, 0o600) 로 먼저 조인다.
       그래야 write 한 비밀이 0644 로 디스크에 내려앉는 창이 없다.
    Windows os.open 은 mode 를 무시 → write_text 동등 + chmod no-op 이중방어.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        path.write_text(content, encoding="utf-8")
        _restrict_perms(path)
        return
    try:
        if os.name != "nt":
            try:
                os.fchmod(fd, 0o600)  # 기존 loose-perm → write 전 조임
            except OSError:
                pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        path.write_text(content, encoding="utf-8")
    _restrict_perms(path)


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
    _write_secret(ENV_FILE, "\n".join(out) + "\n")
    _ok(f"토큰 {_mask(token)} · 채팅 {chat} · 슬롯 {max_slots} (chmod 600)")


def write_hook_env(token: str, chat: str) -> Path:
    """~/.imadhd/env (0600) 에 token/chat 저장. CC 훅 전용 env 파일.

    settings.json global env 대신 → CC 세션/하위 프로세스 전반에 토큰 확산 차단.
    config.Settings.load() 가 이 파일을 자동 로드한다."""
    data_dir = Path(os.environ.get("IMADHD_DATA_DIR", str(Path.home() / ".imadhd")))
    data_dir.mkdir(parents=True, exist_ok=True)
    env_file = data_dir / "env"
    _write_secret(
        env_file,
        f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_ALLOWED_CHAT_ID={chat}\n",
    )
    _ok(f"hook 전용 env → {env_file} (0600, settings.json global env 대신)")
    return env_file


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
    if "imadhd.boot_check" in body:
        return False  # 이미 boot_check 패치 완료
    patched = (
        "@echo off\r\n"
        f'rem patched by imadhd install (PATH-독립 node 절대경로 + boot_check) {datetime.date.today()}\r\n'
        f'"{node}" "{pm2_bin}" resurrect\r\n'
        f'"{PYTHON}" -X utf8 -m imadhd.boot_check\r\n'
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
    # watchdog 기동 (멱등) — 런타임 2차 방어. 부팅 좀비는 1차 boot_check 가,
    # 런타임 heartbeat stale 은 watchdog 이 잡는다.
    if _pm2_has("imadhd-watchdog"):
        _ok("watchdog 이미 online")
    else:
        _run(f'pm2 start "{PYTHON}" --name imadhd-watchdog --cwd "{REPO_DIR}" -- -X utf8 -m imadhd.cli watchdog')
        _ok("watchdog 기동")
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


def _scrub_token_lines(text: str) -> str:
    """raw 텍스트에서 TELEGRAM 시크릿 값 마스킹 (malformed JSON/BOM 대비).

    정상 JSON redaction 은 메모리(dict) 단에서 처리하지만, settings.json 이
    parse 실패(BOM·깨짐)하면 raw 파일을 그대로 .bad-* 로 옮기는 경로에 토큰이
    남는다. 여기선 라인/문자열 단위 regex 로 값만 <redacted> 치환.
    값 폼 세 가지 전부 커버:
      - JSON quoted  : "KEY": "value"
      - JSON unquoted: "KEY": 12345  (숫자 chat id)
      - dotenv       : KEY=value
    """
    import re
    # 값 = "..." | '...' | [^,\\n\\r}]+ (콤마/개행/닫기괄호 전까지 = unquoted).
    # f-string 안 리터럴 } 는 }} 로 escape.
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
        text = re.sub(
            rf'(["\']?{key}["\']?\s*[:=]\s*)(?:"[^"]*"|\'[^\']*\'|[^,\n\r}}]+)',
            r'\1"<redacted>"',
            text,
        )
    return text


def _load_settings() -> dict:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            # parse 실패(BOM·깨짐): 원본을 그대로 옮기면 .bad-* 에 토큰이 남는다.
            # raw 텍스트에서 시크릿 값 마스킹 → 0600 .bad-* 로 저장 + 원본 삭제.
            _warn(f"settings.json 파싱 실패 ({e}) — 시크릿 마스킹 후 백업")
            raw = SETTINGS_FILE.read_text(encoding="utf-8", errors="replace")
            backup = SETTINGS_FILE.with_suffix(f".json.bad-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
            _write_secret(backup, _scrub_token_lines(raw))
            SETTINGS_FILE.unlink()
    return {}


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def step3_hooks(token: str, chat: str) -> None:
    _step(f"Step 3 — Claude Code 훅 자동 추가 → {SETTINGS_FILE}")
    data = _load_settings()
    # 마이그레이션 먼저(메모리 redaction) — 백업 파일에 토큰이 잔류하지 않도록.
    # 예전 설치가 settings.json global env 에 넣어둔 TELEGRAM_BOT_TOKEN /
    # TELEGRAM_ALLOWED_CHAT_ID 제거. 토큰은 이제 write_hook_env() 가 만든
    # ~/.imadhd/env (0600) 로 격리 → CC 세션/하위 프로세스 전반 토큰 확산 차단.
    # env 블록이 비면 키 자체도 정리.
    env_block = data.get("env")
    if isinstance(env_block, dict):
        leaked = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID") if k in env_block]
        for k in leaked:
            env_block.pop(k, None)
        if leaked:
            _ok(f"global env 토큰 {len(leaked)}개 제거 → ~/.imadhd/env 로 이전 (확산 차단)")
        if not env_block:
            data.pop("env", None)
            if leaked:
                _ok("빈 env 블록 정리")
    # 백업 = redacted 스냅샷(메모리 data). 디스크 원본을 그대로 복사하면 마이그레이션
    # 전 토큰이 .bak 파일에 남는다. redacted 상태로 0600 보존.
    if SETTINGS_FILE.exists():
        bak = SETTINGS_FILE.with_suffix(f".json.bak-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
        _write_secret(bak, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        _ok(f"백업(redacted, 0600) → {bak.name}")
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
    write_hook_env(token, chat)

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
