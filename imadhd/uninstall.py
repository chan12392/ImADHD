"""imadhd uninstall — 원라인 깔끔 제거 (install 의 역순).

제거 대상(전부 멱등 — 없으면 스킵):
  1. pm2 imadhd 프로세스 + pm2 save (+ Windows schtask / Linux systemd 안내)
  2. 텔레그램 봇 명령 메뉴에서 ImADHD 명령만外科적 제거(사용자 커스텀 보존)
  3. Claude Code settings.json 의 imadhd 훅 4개 제거(redacted 백업 후)
  4. 핀 메시지 unpin(best-effort)
  5. data_dir(~/.imadhd, 토큰 env 포함) 전체 삭제
  6. repo/.env 에서 ImADHD 키 제거(남는 키 없으면 파일 삭제)

사용:
  python -m imadhd uninstall            # 확인 프롬프트
  python -m imadhd uninstall --yes      # 비대화형(자동화)
  python -m imadhd uninstall --skip-pm2 # pm2 단계 건너뛰기

파괴적 → 기본 확인 프롬프트. 토큰은 어디에도 로그 안 함.
패키지 자체(repo 디렉토리·pip 패키지)는 사용자가 직접 제거.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import install as I   # 로거·헬퍼 재사용(_run/_which/_pm2_has/_scrub_token_lines/_write_secret)

_step, _ok, _warn, _fail = I._step, I._ok, I._warn, I._fail
SETTINGS_FILE = I.SETTINGS_FILE
ENV_FILE = I.ENV_FILE
REPO_DIR = I.REPO_DIR

# install.HOOK_DEFS 의 module 들(훅 제거 매칭용).
HOOK_MODULES = ("imadhd.hooks.register_hook", "imadhd.hooks.reply_hook",
                "imadhd.hooks.ask_hook", "imadhd.hooks.busy_hook")


def _data_dir() -> Path:
    return Path(os.environ.get("IMADHD_DATA_DIR", str(Path.home() / ".imadhd")))


def _read_token_chat(args) -> tuple[str, str]:
    """토큰/챗 확정: --token 인자 > data_dir/env > repo/.env. 없으면 ('','')."""
    token = (args.token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (args.chat or os.environ.get("TELEGRAM_ALLOWED_CHAT_ID") or "").strip()
    dd_env = _data_dir() / "env"
    for src in (dd_env, ENV_FILE):
        if not src.exists():
            continue
        for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN=") and not token:
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TELEGRAM_ALLOWED_CHAT_ID=") and not chat:
                chat = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token, chat


# ============ Step 1: pm2 ============
def _find_pm2_imadhd_procs() -> list[str]:
    """pm2 jlist 에서 imadhd 계열 프로세스 이름 수집."""
    r = I._run("pm2 jlist", check=False, capture=True)
    if r.returncode != 0 or not r.stdout:
        return []
    try:
        procs = json.loads(r.stdout)
    except Exception:
        return []
    out = []
    for p in procs:
        name = (p.get("name") or "")
        script = ((p.get("pm2_env") or {}).get("pm_exec_path") or "")
        if "imadhd" in name.lower() or "imadhd" in script.lower():
            out.append(name)
    return out


def _remove_schtask_windows() -> None:
    """install._register_schtask 가 만든 'imadhd-pm2-resurrect' 스케줄 작업 제거."""
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Unregister-ScheduledTask -TaskName 'imadhd-pm2-resurrect' -Confirm:$false"
    )
    import subprocess
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode == 0:
        _ok("schtask 'imadhd-pm2-resurrect' 제거")
    else:
        _warn("schtask 제거 스킵(없음 또는 권한 부족)")


def remove_pm2(skip: bool) -> None:
    _step("Step 1 — pm2 프로세스 제거")
    if skip:
        _warn("건너뜀 (--skip-pm2)")
        return
    if not I._which("pm2"):
        _warn("pm2 미설치 — 건너뜀")
        return
    names = _find_pm2_imadhd_procs()
    if not names:
        _ok("pm2 imadhd 프로세스 없음")
    else:
        for name in names:
            I._run(f'pm2 delete "{name}"', check=False)
            _ok(f"pm2 delete {name}")
        I._run("pm2 save", check=False)
        _ok("pm2 save (dump 갱신)")
    if os.name == "nt":
        _remove_schtask_windows()
    else:
        # systemd unit 제거는 sudo 필요 → 안내만.
        _warn("Linux: 부팅 자동복구 systemd unit 은 `sudo pm2 unstartup systemd` 로 직접 제거")


# ============ Step 2: 봇 명령 메뉴 ============
def remove_bot_menu(token: str, max_slots: int) -> None:
    _step("Step 2 — 텔레그램 봇 명령 메뉴에서 ImADHD 제거 (사용자 커스텀 보존)")
    if not token:
        _warn("토큰 없음 — 봇 메뉴 제거 스킵 (data_dir/env 또는 --token 필요)")
        return
    try:
        from .telegram_api.client import TelegramClient
        from .setup_commands import build_commands
        import tempfile
    except Exception as e:
        _warn(f"모듈 import 실패 ({e}) — 스킵")
        return
    off = Path(tempfile.gettempdir()) / "imadhd_uninstall_offset.txt"
    tg = TelegramClient(token, off, None)
    ours_names = {c["command"] for c in build_commands(max_slots)}
    for label, scope in [("default", None), ("DM(private)", {"type": "all_private_chats"})]:
        try:
            existing = tg.get_my_commands(scope) or []
        except Exception as e:
            _warn(f"{label} 명령 조회 실패 ({e}) — 스킵")
            continue
        kept = [c for c in existing if c.get("command") not in ours_names]
        removed = len(existing) - len(kept)
        if not kept:
            try:
                tg.delete_my_commands(scope)
            except Exception:
                pass
            _ok(f"{label}: ImADHD {removed}건 제거 (빈 스코프 → deleteMyCommands)")
        else:
            try:
                tg.set_my_commands(kept, scope)
            except Exception as e:
                _warn(f"{label} 재설정 실패 ({e})")
                continue
            _ok(f"{label}: ImADHD {removed}건 제거, 사용자 명령 {len(kept)}건 보존")


# ============ Step 3: Claude Code 훅 ============
def remove_hooks() -> None:
    _step(f"Step 3 — Claude Code 훅 제거 → {SETTINGS_FILE}")
    if not SETTINGS_FILE.exists():
        _warn("settings.json 없음 — 스킵")
        return
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _warn(f"settings.json 파싱 실패 ({e}) — 훅 제거 스킵")
        return
    # 백업 = redacted 스냅샷(0600). 훅 제거 전 보존.
    import datetime
    bak = SETTINGS_FILE.with_suffix(
        f".json.bak-uninstall-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    I._write_secret(bak, I._scrub_token_lines(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n"))
    _ok(f"백업(redacted, 0600) → {bak.name}")

    hooks = data.get("hooks", {})
    removed = 0
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for g in groups:
            blob = json.dumps(g, ensure_ascii=False)
            if any(mod in blob for mod in HOOK_MODULES):
                removed += 1           # imadhd 훅 그룹 → 드롭
            else:
                kept_groups.append(g)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            hooks.pop(event, None)     # 빈 이벤트 키 정리
    if not hooks:
        data.pop("hooks", None)
    # I._save_settings 쓰면 install.py 의 SETTINGS_FILE(미패치 실경로) 에 쓴다.
    # uninstall 이 잡은 SETTINGS_FILE(tmp/타깃) 에 직접 내려야 한다.
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _ok(f"imadhd 훅 {removed}개 제거 (사용자 훅/설정 전부 보존)")


# ============ Step 4: 핀 unpin (best-effort) ============
def remove_pin(token: str, chat: str) -> None:
    _step("Step 4 — 텔레그램 핀 메시지 unpin (best-effort)")
    if not token or not chat:
        _warn("토큰/챗 없음 — unpin 스킵")
        return
    dd = _data_dir()
    sid_file = dd / "pin_message_id.txt"
    if not sid_file.exists():
        _warn("핀 id 파일 없음 — unpin 스킵")
        return
    try:
        mid = int(sid_file.read_text(encoding="utf-8").strip())
    except Exception:
        _warn("핀 id 읽기 실패 — unpin 스킵")
        return
    try:
        from .telegram_api.client import TelegramClient
        import tempfile
        off = Path(tempfile.gettempdir()) / "imadhd_uninstall_offset.txt"
        tg = TelegramClient(token, off, chat)
        # unpinChatMessage + deleteMessage 로 보드 제거. 실패해도 다음 단계 진행.
        try:
            tg._api("unpinChatMessage", {"chat_id": chat, "message_id": mid}, timeout=10)
        except Exception:
            pass
        try:
            tg.delete_message(chat, mid)
        except Exception:
            pass
        _ok(f"핀 메시지 {mid} unpin/delete")
    except Exception as e:
        _warn(f"unpin 실패 ({e}) — 텔레그램에서 수동 삭제 가능")


# ============ Step 5: data_dir ============
def remove_data_dir() -> None:
    _step("Step 5 — data_dir 삭제 (토큰 env 포함)")
    dd = _data_dir()
    if not dd.exists():
        _warn(f"data_dir 없음 ({dd}) — 스킵")
        return
    try:
        shutil.rmtree(dd)
        _ok(f"data_dir 삭제 → {dd}")
    except Exception as e:
        _fail(f"data_dir 삭제 실패 ({e}) — 수동 삭제: {dd}")


# ============ Step 6: repo/.env ============
def remove_env_file() -> None:
    _step(f"Step 6 — repo/.env 에서 ImADHD 키 제거")
    if not ENV_FILE.exists():
        _warn(".env 없음 — 스킵")
        return
    imadhd_keys = {
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "IMADHD_MAX_SLOTS",
        "IMADHD_TRANSPORT", "IMADHD_REPLY_MARKER", "IMADHD_DATA_DIR",
        "IMADHD_ALLOW_ANY_CHAT",
    }
    kept: list[str] = []
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in imadhd_keys:
            continue
        kept.append(line)
    # ImADHD 키만 있었으면 파일 자체 삭제(토큰 잔류 방지). 다른 키 남으면 안전 재기록.
    if not kept or all(not l.strip() for l in kept):
        try:
            ENV_FILE.unlink()
            _ok(".env 삭제 (ImADHD 키만 존재)")
        except Exception as e:
            _fail(f".env 삭제 실패 ({e}) — 수동 삭제: {ENV_FILE}")
        return
    try:
        I._write_secret(ENV_FILE, "\n".join(kept).rstrip() + "\n")
        _ok(f".env 에서 ImADHD 키 제거, 사용자 키 {sum(1 for l in kept if '=' in l)}건 보존")
    except Exception as e:
        _fail(f".env 재기록 실패 ({e})")


# ============ main ============
def _print_plan(token_present: bool, max_slots: int) -> None:
    print("\n제거 대상:")
    print("  1. pm2 imadhd 프로세스 (+ Windows schtask / Linux systemd 안내)")
    print(f"  2. 텔레그램 봇 명령 메뉴: ImADHD {max_slots}+건 (사용자 커스텀 보존)")
    print("  3. Claude Code settings.json imadhd 훅 4개 (redacted 백업)")
    print("  4. 텔레그램 핀 메시지 unpin/delete (best-effort)")
    print(f"  5. data_dir 전체 삭제: {_data_dir()}  (토큰 env 포함)")
    print(f"      └ 토큰 보유: {'있음(봇 메뉴·unpin 수행)' if token_present else '없음(해당 단계 스킵)'}")
    print(f"  6. repo/.env: {ENV_FILE} 에서 ImADHD 키 제거")
    print("\n※ 패키지 디렉토리(이 repo)·pip 패키지는 직접 제거하세요.")
    print("※ 토큰은 어디에도 출력되지 않습니다.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="imadhd uninstall", description="ImADHD 원라인 제거")
    ap.add_argument("--token", help="Telegram bot token (봇 메뉴/unpin용. 없으면 env 자동 탐색)")
    ap.add_argument("--chat", help="본인 Telegram user id (unpin용)")
    ap.add_argument("--max-slots", type=int, default=6)
    ap.add_argument("--yes", action="store_true", help="확인 프롬프트 생략(비대화형)")
    ap.add_argument("--skip-pm2", action="store_true", help="pm2 단계 건너뛰기")
    args = ap.parse_args(argv)

    print("=" * 60)
    print(" ImADHD uninstaller — 깔끔 제거")
    print("=" * 60)

    token, chat = _read_token_chat(args)
    _print_plan(bool(token), args.max_slots)

    if not args.yes:
        if not sys.stdin.isatty():
            _fail("비대화형 환경 — `--yes` 플래그 필요")
            return 2
        print()
        ans = input("전체 제거 진행? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            _warn("중단 — 아무것도 변경하지 않음")
            return 130

    remove_pm2(args.skip_pm2)
    remove_bot_menu(token, args.max_slots)
    remove_hooks()
    remove_pin(token, chat)
    remove_data_dir()
    remove_env_file()

    _step("완료")
    _ok("ImADHD 제거 완료. 남은 repo 디렉토리는 `rm -rf` 로 직접 삭제.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _warn("사용자 중단")
        sys.exit(130)
    except Exception as e:
        _fail(f"제거 중단: {e}")
        sys.exit(1)
