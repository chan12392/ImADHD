"""/doctor 진단 명령 단위 테스트.

각 검사(heartbeat/registry/pin/hooks/pm2/bot menu)가 정상·장애 상황에서
✅/⚠️/❌ 마커로 분기하는지 검증. 외부(pm2·텔레그램 API)는 monkeypatch 로 격리.
"""
import json
import time
from pathlib import Path

from imadhd.commands.base import Message, CommandContext
from imadhd.commands.doctor_command import DoctorCommand


class FakeInfo:
    def __init__(self, number, status="idle"):
        self.number = number
        self.status = status


class FakeRegistry:
    def __init__(self, infos=None):
        self._infos = infos or []

    def active(self):
        return self._infos


class FakeTelegram:
    """get_my_commands 만 지원하는 페이크(네트워크 없음)."""
    def __init__(self, default_cmds=None, private_cmds=None, error=None):
        self._default = default_cmds or []
        self._private = private_cmds or []
        self._error = error
        self.sent = []

    def get_my_commands(self, scope=None):
        if self._error:
            raise self._error
        return list(self._private) if scope else list(self._default)

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


class FakeSettings:
    def __init__(self, data_dir, max_slots=6):
        self.data_dir = Path(data_dir)
        self.max_slots = max_slots
        self.heartbeat_path = self.data_dir / "heartbeat.txt"


def _ctx(tmp_path, *, reg=None, tg=None):
    return CommandContext(
        settings=FakeSettings(tmp_path),
        registry=reg or FakeRegistry(),
        transport=None,
        telegram=tg or FakeTelegram(),
    )


# ---------- match ----------

def test_match_doctor_triggers():
    c = DoctorCommand()
    assert c.match(Message("1", "/doctor", {}))
    assert c.match(Message("1", "/진단", {}))
    assert c.match(Message("1", "/status", {}))
    assert not c.match(Message("1", "/doctorr", {}))


# ---------- heartbeat ----------

def test_heartbeat_fresh_is_ok(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.settings.heartbeat_path.write_text(str(time.time()), encoding="utf-8")
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("✅ 라우터 생존" in t for t in ctx.telegram.sent)


def test_heartbeat_stale_is_warning(tmp_path):
    ctx = _ctx(tmp_path)
    old = time.time() - 120   # 2분 전 = 사망 의심
    ctx.settings.heartbeat_path.write_text(str(old), encoding="utf-8")
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("⚠️" in t and "heartbeat" in t for t in ctx.telegram.sent)


def test_heartbeat_missing_is_error(tmp_path):
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("❌ heartbeat" in t for t in ctx.telegram.sent)


# ---------- registry ----------

def test_registry_reports_active_and_busy(tmp_path):
    reg = FakeRegistry([FakeInfo(1), FakeInfo(2, "busy")])
    ctx = _ctx(tmp_path, reg=reg)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("슬롯 2/6 활성 (1 작업중)" in t for t in ctx.telegram.sent)


# ---------- pin ----------

def test_pin_present(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.settings.data_dir / "pin_message_id.txt").write_text("123", encoding="utf-8")
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("✅ 핀 본문 존재" in t for t in ctx.telegram.sent)


def test_pin_missing(tmp_path):
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("⚠️ 핀 본문 없음" in t for t in ctx.telegram.sent)


# ---------- hooks ----------

def test_hooks_all_present(tmp_path, monkeypatch):
    settings_dir = tmp_path / "fakehome" / ".claude"
    settings_dir.mkdir(parents=True)
    hooks = {
        "SessionStart": [{"hooks": [{"command": "python -m imadhd.hooks.register_hook"}]}],
        "Stop": [{"hooks": [{"command": "python -m imadhd.hooks.reply_hook"}]}],
        "PreToolUse": [{"hooks": [{"command": "python -m imadhd.hooks.dispatch_hook"}]}],
        "UserPromptSubmit": [{"hooks": [{"command": "python -m imadhd.hooks.busy_hook"}]}],
    }
    (settings_dir / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("✅ 훅 4/4" in t for t in ctx.telegram.sent)


def test_hooks_missing_reports_which(tmp_path, monkeypatch):
    settings_dir = tmp_path / "fakehome" / ".claude"
    settings_dir.mkdir(parents=True)
    # Stop 만 설치, 나머지 누락
    hooks = {"Stop": [{"hooks": [{"command": "imadhd.hooks.reply_hook"}]}]}
    (settings_dir / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    msg = [t for t in ctx.telegram.sent if "훅" in t][0]
    assert "❌" in msg
    assert "SessionStart" in msg   # 누락된 것 명시


# ---------- bot menu ----------

def test_bot_menu_use_in_both_scopes(tmp_path):
    tg = FakeTelegram(
        default_cmds=[{"command": "use"}],
        private_cmds=[{"command": "use"}],
    )
    ctx = _ctx(tmp_path, tg=tg)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("✅ 봇 메뉴 default+private /use 포함" in t for t in ctx.telegram.sent)


def test_bot_menu_use_missing(tmp_path):
    tg = FakeTelegram(default_cmds=[], private_cmds=[])
    ctx = _ctx(tmp_path, tg=tg)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("❌ 봇 메뉴 /use 없음" in t for t in ctx.telegram.sent)


# ---------- pm2 ----------

def test_pm2_not_installed(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr("imadhd.commands.doctor_command.subprocess.run", boom)
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("⚠️ pm2 미설치" in t for t in ctx.telegram.sent)


def test_pm2_router_online(tmp_path, monkeypatch):
    procs = [{
        "name": "claude-imadhd-router",
        "pm2_env": {"status": "online", "pm_exec_path": "/x/imadhd/router.py", "autorestart": True},
    }]

    class FakeResult:
        returncode = 0
        stdout = json.dumps(procs)
    monkeypatch.setattr(
        "imadhd.commands.doctor_command.subprocess.run",
        lambda *a, **k: FakeResult(),
    )
    ctx = _ctx(tmp_path)
    DoctorCommand().handle(Message("1", "/doctor", {}), ctx)
    assert any("✅ pm2" in t and "online" in t for t in ctx.telegram.sent)
