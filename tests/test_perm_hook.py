"""perm_hook 단위 테스트.

위험 분류와 승인 전송 실패 시 fail-closed 동작을 검증한다.
"""
import io
import json

from imadhd.hooks import perm_hook
from imadhd.hooks.perm_hook import build_approval_body, classify_risk, DANGEROUS_PATTERNS


# ───────────────────────── 안전 명령 (None 반환) ─────────────────────────

def test_safe_commands_not_flagged():
    """일반 개발 명령 = 게이트 통과(텔레그램 미송신)."""
    safe = [
        "ls -la", "cat file.txt", "echo hello", "pwd",
        "git status", "git diff", "git log --oneline",
        "py -m pytest -q", "npm install", "python script.py",
        "cd build && make", "grep -r foo .", "type notes.md",
    ]
    for cmd in safe:
        assert classify_risk("Bash", {"command": cmd}) is None, cmd


def test_non_bash_tools_not_gated():
    """Write/Edit = 1차 미게이트(보호디렉토리 차기 확장). None 반환."""
    assert classify_risk("Write", {"file_path": "/etc/passwd", "content": "x"}) is None
    assert classify_risk("Edit", {"file_path": "x", "old_string": "a", "new_string": "b"}) is None
    assert classify_risk("Read", {"file_path": "x"}) is None


def test_empty_command_is_safe():
    assert classify_risk("Bash", {"command": ""}) is None
    assert classify_risk("Bash", {}) is None


# ───────────────────────── 위험 명령 (요약 반환) ─────────────────────────

def test_dangerous_rm_flagged():
    s = classify_risk("Bash", {"command": "rm -rf build/"})
    assert s is not None
    assert "rm -rf build/" in s


def test_dangerous_git_push_flagged():
    assert classify_risk("Bash", {"command": "git push origin main"}) is not None
    assert classify_risk("Bash", {"command": "git reset --hard HEAD~3"}) is not None
    assert classify_risk("Bash", {"command": "git clean -fdx"}) is not None


def test_dangerous_kill_flagged():
    assert classify_risk("Bash", {"command": "kill -9 1234"}) is not None
    assert classify_risk("Bash", {"command": "taskkill /PID 456 /F"}) is not None


def test_dangerous_pm2_flagged():
    assert classify_risk("Bash", {"command": "pm2 restart imadhd"}) is not None
    assert classify_risk("Bash", {"command": "pm2 delete 0"}) is not None


def test_dangerous_sudo_flagged():
    assert classify_risk("Bash", {"command": "sudo apt update"}) is not None


def test_dangerous_drop_flagged():
    assert classify_risk("Bash", {"command": "psql -c 'DROP TABLE users'"}) is not None


def test_dangerous_systemctl_flagged():
    assert classify_risk("Bash", {"command": "systemctl restart nginx"}) is not None


def test_dangerous_case_insensitive():
    """대소문자 무관 매칭(RM, Git PUSH)."""
    assert classify_risk("Bash", {"command": "RM -rf x"}) is not None
    assert classify_risk("Bash", {"command": "GIT PUSH"}) is not None


# ───────────────────────── 오탐 가드 ─────────────────────────

def test_word_boundary_no_false_positive():
    """rm 단어가 다른 단어 일부면 매칭 안 됨(form, harm, warm 등)."""
    # 'rm' 가 단어 경계 안 옴 → 안전
    assert classify_risk("Bash", {"command": "echo harm warm form"}) is None
    # 'kill' 도 마찬가지
    assert classify_risk("Bash", {"command": "echo skill killed-task"}) is None


def test_summary_truncates_long_command():
    """과도한 길이 command → 800자 절단(텔레그램 표시)."""
    long_cmd = "rm " + "x" * 2000
    s = classify_risk("Bash", {"command": long_cmd})
    assert s is not None
    assert len(s) <= 800


def test_approval_body_escapes_html_summary():
    body = build_approval_body("", "Bash", "rm -rf a && echo <token>")
    assert "<code>" in body
    assert "&&" not in body
    assert "<token>" not in body
    assert "rm -rf a &amp;&amp; echo &lt;token&gt;" in body


def test_send_failure_denies_instead_of_fail_open(monkeypatch, tmp_path):
    """승인 메시지 전송 실패 시 위험 명령을 조용히 통과시키지 않는다."""
    from imadhd import config
    from imadhd.core import registry
    from imadhd.telegram_api import client

    class FakeSettings:
        bot_token = "token"
        allowed_chat_id = "42"
        offset_path = tmp_path / "offset.txt"
        registry_path = tmp_path / "registry.json"
        data_dir = tmp_path
        max_slots = 6
        reply_marker = "[A.D.H.D]"

    class FakeInfo:
        number = 3

    class FakeRegistry:
        def __init__(self, *_args, **_kwargs):
            pass

        def find_by_session(self, _session_id):
            return FakeInfo()

    class FailingTelegram:
        def __init__(self, *_args, **_kwargs):
            pass

        def send(self, *_args, **_kwargs):
            raise RuntimeError("telegram html parse failed")

    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf a && echo <token>"},
        "session_id": "s1",
        "transcript_path": str(tmp_path / "t.jsonl"),
    }

    monkeypatch.setattr(config.Settings, "load", classmethod(lambda cls: FakeSettings()))
    monkeypatch.setattr(registry, "JSONFileRegistry", FakeRegistry)
    monkeypatch.setattr(client, "TelegramClient", FailingTelegram)
    monkeypatch.setattr(perm_hook, "_origin_has_marker", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(perm_hook.sys, "stdin", io.StringIO(json.dumps(payload)))
    stdout = io.StringIO()
    monkeypatch.setattr(perm_hook.sys, "stdout", stdout)

    assert perm_hook.main() == 0
    out = json.loads(stdout.getvalue())
    hook = out["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"
    assert "전송 실패" in hook["reason"]
