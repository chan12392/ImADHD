"""uninstall 단위 테스트.

파괴적 연산 → 멱등성·사용자 자산(훅/봇메뉴/.env) 보존·토큰 잔류 방지에 집중.
실제 pm2/텔레그램 API 는 monkeypatch 로 격리.
"""
import json
import sys
from pathlib import Path

import imadhd.uninstall as U
from imadhd.uninstall import main as uninstall_main


# ---------- 헬퍼: imadhd.install 의 경로를 tmp 로 치환
def _patch_paths(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    claude = home / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = repo / ".env"
    monkeypatch.setattr(U, "SETTINGS_FILE", settings)
    monkeypatch.setattr(U, "ENV_FILE", env_file)
    monkeypatch.setattr(U, "REPO_DIR", repo)
    # _data_dir() 도 tmp 기반으로
    dd = tmp_path / "imadhd-data"
    monkeypatch.setenv("IMADHD_DATA_DIR", str(dd))
    # 실 env 토큰이 테스트로 새어들어가는 것 차단(토큰 평문 출력 방지).
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    return {"settings": settings, "env": env_file, "data_dir": dd, "home": home}


# ============ Step 3: 훅 제거 ============

def test_remove_hooks_strips_imadhd_keeps_user_hooks(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    user_hook = {"hooks": [{"type": "command", "command": "echo user-thing"}]}
    data = {
        "hooks": {
            "SessionStart": [
                user_hook,
                {"hooks": [{"command": "python -m imadhd.hooks.register_hook"}]},
            ],
            "Stop": [{"hooks": [{"command": "imadhd.hooks.reply_hook"}]}],
            "PreToolUse": [{"hooks": [{"command": "imadhd.hooks.ask_hook"}],
                            "matcher": "AskUserQuestion"}],
            "UserPromptSubmit": [{"hooks": [{"command": "imadhd.hooks.busy_hook"}]}],
        },
        "otherSetting": 123,
    }
    p["settings"].write_text(json.dumps(data), encoding="utf-8")
    U.remove_hooks()
    out = json.loads(p["settings"].read_text(encoding="utf-8"))
    # 사용자 훅 보존
    assert out["hooks"]["SessionStart"] == [user_hook]
    # imadhd-only 이벤트 키는 통째로 제거
    assert "Stop" not in out["hooks"]
    assert "PreToolUse" not in out["hooks"]
    assert "UserPromptSubmit" not in out["hooks"]
    # 사용자 설정 보존
    assert out["otherSetting"] == 123


def test_remove_hooks_creates_redacted_backup(monkeypatch, tmp_path):
    """훅 제거 전 redacted 백업 생성(토큰 잔류 방지)."""
    p = _patch_paths(monkeypatch, tmp_path)
    data = {"hooks": {"Stop": [{"hooks": [{"command": "imadhd.hooks.reply_hook"}]}]}}
    p["settings"].write_text(json.dumps(data), encoding="utf-8")
    U.remove_hooks()
    baks = list(p["settings"].parent.glob("settings.json.bak-uninstall-*"))
    assert baks, "백업 파일 생성돼야 함"


def test_remove_hooks_idempotent_no_settings(monkeypatch, tmp_path):
    """settings.json 없으면 스킵(예외 없이)."""
    _patch_paths(monkeypatch, tmp_path)
    U.remove_hooks()   # 예외 나면 안 됨


# ============ Step 6: .env ============

def test_remove_env_file_pure_imadhd_deletes(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    p["env"].write_text(
        "TELEGRAM_BOT_TOKEN=123:ABC\nTELEGRAM_ALLOWED_CHAT_ID=999\nIMADHD_MAX_SLOTS=6\n",
        encoding="utf-8",
    )
    U.remove_env_file()
    assert not p["env"].exists(), "ImADHD-only .env 는 파일 삭제(토큰 잔류 방지)"


def test_remove_env_file_preserves_user_keys(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    p["env"].write_text(
        "MY_APP_KEY=keep\nTELEGRAM_BOT_TOKEN=123:ABC\nMY_OTHER=x\n",
        encoding="utf-8",
    )
    U.remove_env_file()
    remaining = p["env"].read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in remaining
    assert "123:ABC" not in remaining
    assert "MY_APP_KEY=keep" in remaining
    assert "MY_OTHER=x" in remaining


def test_remove_env_file_idempotent_missing(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    # .env 없음
    U.remove_env_file()


# ============ Step 5: data_dir ============

def test_remove_data_dir_wipes(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    dd = Path(__import__("os").environ["IMADHD_DATA_DIR"])
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "env").write_text("TELEGRAM_BOT_TOKEN=secret", encoding="utf-8")
    (dd / "registry.json").write_text("{}", encoding="utf-8")
    U.remove_data_dir()
    assert not dd.exists()


def test_remove_data_dir_idempotent(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    U.remove_data_dir()   # 없어도 OK


# ============ Step 2: 봇 메뉴 ============

class _FakeTG:
    """get_my_commands/set_my_commands/delete_my_commands 기록."""
    def __init__(self, existing_default, existing_private):
        self._cmds = {None: list(existing_default),
                      "all_private_chats": list(existing_private)}
        self.set_calls = []
        self.delete_calls = []
    def get_my_commands(self, scope=None):
        key = (scope or {}).get("type") if scope else None
        return list(self._cmds.get(key, []))
    def set_my_commands(self, cmds, scope=None):
        self.set_calls.append((scope, list(cmds)))
    def delete_my_commands(self, scope=None):
        self.delete_calls.append(scope)


def test_remove_bot_menu_filters_imadhd_keeps_user(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    # default 에 imadhd + 사용자 커스텀 섞임
    fake = _FakeTG(
        existing_default=[{"command": "1"}, {"command": "use"}, {"command": "myown"}],
        existing_private=[{"command": "list"}, {"command": "weather"}],
    )
    monkeypatch.setattr(
        "imadhd.telegram_api.client.TelegramClient",
        lambda *a, **k: fake,
    )
    U.remove_bot_menu(token="tok", max_slots=6)
    # default: 사용자 myown 보존, 1·use 제거
    scope_none, kept_default = fake.set_calls[0]
    kept_default_names = {c["command"] for c in kept_default}
    assert "myown" in kept_default_names
    assert "1" not in kept_default_names
    assert "use" not in kept_default_names


def test_remove_bot_menu_no_token_skips(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    # 토큰 없으면 조용히 스킵(예외 없이)
    U.remove_bot_menu(token="", max_slots=6)


# ============ Step 1: pm2 ============

def test_find_pm2_procs_detects_imadhd(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    class FakeResult:
        returncode = 0
        stdout = json.dumps([
            {"name": "chleo-imadhd-router", "pm2_env": {"pm_exec_path": "/x/imadhd/cli.py"}},
            {"name": "other-app", "pm2_env": {"pm_exec_path": "/y/main.js"}},
        ])
    monkeypatch.setattr(U.I, "_which", lambda n: "/fake/pm2")
    monkeypatch.setattr(U.I, "_run", lambda *a, **k: FakeResult())
    names = U._find_pm2_imadhd_procs()
    assert names == ["chleo-imadhd-router"]


def test_remove_pm2_no_pm2_binary(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(U.I, "_which", lambda n: None)
    U.remove_pm2(skip=False)   # 예외 없이 스킵


def test_remove_pm2_skip_flag(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    U.remove_pm2(skip=True)


# ============ main: 확인 게이트 ============

def test_main_noninteractive_without_yes_exits_2(monkeypatch, tmp_path):
    """비대화형(non-tty) + --yes 없으면 중단(exit 2, 아무 변경 없음)."""
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"isatty": lambda self: False})())
    rc = uninstall_main(["--yes"][:0] or [])   # 인자 없음 = --yes 없음
    assert rc == 2


def test_main_yes_flag_runs_all_steps(monkeypatch, tmp_path):
    """--yes 면 전체 단계 실행(각 단계는 스킵 가능해야)."""
    p = _patch_paths(monkeypatch, tmp_path)
    # settings.json 에 imadhd 훅
    p["settings"].write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "imadhd.hooks.reply_hook"}]}]}}),
        encoding="utf-8",
    )
    # pm2 없음으로 단순화
    monkeypatch.setattr(U.I, "_which", lambda n: None)
    rc = uninstall_main(["--yes", "--skip-pm2"])
    assert rc == 0
    out = json.loads(p["settings"].read_text(encoding="utf-8"))
    assert "hooks" not in out or "Stop" not in out.get("hooks", {})


# ============ 토큰 탐지 ============

def test_read_token_chat_from_data_dir_env(monkeypatch, tmp_path):
    p = _patch_paths(monkeypatch, tmp_path)
    dd = Path(__import__("os").environ["IMADHD_DATA_DIR"])
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "env").write_text("TELEGRAM_BOT_TOKEN=999:FROM-DD\nTELEGRAM_ALLOWED_CHAT_ID=42\n",
                            encoding="utf-8")
    args = type("A", (), {"token": "", "chat": ""})()
    token, chat = U._read_token_chat(args)
    assert token == "999:FROM-DD"
    assert chat == "42"
