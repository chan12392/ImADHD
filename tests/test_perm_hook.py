"""perm_hook 단위 테스트 (classify_risk 위험 매칭).

main() 은 Settings/Telegram/폴링 의존 → classify_risk 순수 함수만 단위 테스트.
라이브 프로브(실제 CC 차단)는 대표님 텔레그램 검증 단계.
"""
from imadhd.hooks.perm_hook import classify_risk, DANGEROUS_PATTERNS


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
