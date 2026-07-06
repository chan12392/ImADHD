"""/open 단일 명령 회귀 테스트 (2026-07-06 단순화).

/open 은 단일 명령만: 모델/provider 변형(/open glm, /open sonnet, /open opus 등)
전부 제거. 항상 기본 claude + 홈 cwd. CC 가 홈 기반 프로젝트로 인식해
resume 세션 목록 노출이 목적.
"""
from pathlib import Path

from imadhd.commands.base import Message
from imadhd.commands.open_command import (
    OpenCommand,
    build_open_env,
)


def _polluted_env():
    """z.ai 프록시 + CC identity 오염 env (제거 검증용)."""
    return {
        "HOME": "C:\\Users\\user",
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "secret-token",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.2",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "old-parent",
        "AI_AGENT": "x",
        "PATH": "C:\\Windows",
    }


# ---------- match() ----------

def test_open_bare_matches():
    c = OpenCommand()
    assert c.match(Message("1", "/open", {}))


def test_open_variants_do_not_match():
    """/open 단일만. 변형(모델/glm/경로)은 미매치."""
    c = OpenCommand()
    for txt in ["/open glm", "/open sonnet", "/open opus",
                "/open claude-opus-4-8", "/open C:\\proj", "/open 1"]:
        assert not c.match(Message("1", txt, {})), f"{txt} 는 매치되면 안 됨"


# ---------- build_open_env() ----------

def test_build_open_env_sets_home_cwd():
    env = build_open_env(_polluted_env())
    assert env["IMADHD_CC_CWD"] == str(Path.home())


def test_build_open_env_strips_claude_identity():
    """CLAUDE*/AI_AGENT identity env 제거(transcript 누락 회귀 방지)."""
    env = build_open_env(_polluted_env())
    for k in list(env):
        assert not (k == "AI_AGENT" or k.startswith("CLAUDE")), f"{k} 잔존"
    # z.ai 프록시 키도 이제 항상 제거(/open 단일화 — use_glm 분기 제거).
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        assert k not in env


def test_build_open_env_does_not_mutate_input():
    src = _polluted_env()
    build_open_env(src)
    assert "ANTHROPIC_BASE_URL" in src  # 원본 스타일 dict 는 건드리지 않음


# ---------- handle() — spawn 커맨드라인 검증 ----------

class _FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def _handle_and_capture(monkeypatch, text):
    from imadhd.commands.base import CommandContext
    import imadhd.commands.open_command as oc

    # Windows 분기(subprocess.Popen) 검증. os.name=nt 고정.
    monkeypatch.setattr(oc.os, "name", "nt")

    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")

        class _P:
            pass
        return _P()

    monkeypatch.setattr(oc.subprocess, "Popen", fake_popen)
    tg = _FakeTelegram()
    ctx = CommandContext(settings=None, registry=None, transport=None, telegram=tg)
    oc.OpenCommand().handle(Message("1", text, {}), ctx)
    return captured, tg


def test_handle_bare_open_uses_host_and_home_cwd(monkeypatch):
    captured, tg = _handle_and_capture(monkeypatch, "/open")
    # inner = `cd /d <repo> && py -m imadhd.host -- claude`
    inner = captured["args"][-1]
    assert "imadhd.host" in inner
    assert "claude" in inner
    assert "--model" not in inner  # 모델 인자 제거
    assert inner.endswith("claude")
    # env 에 홈 cwd 주입
    assert captured["env"]["IMADHD_CC_CWD"] == str(Path.home())
    # 답장에 홈 경로 표시
    assert str(Path.home()) in tg.sent[-1]
