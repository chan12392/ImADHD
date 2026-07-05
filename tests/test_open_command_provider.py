"""/open provider/모델 선택 회귀 테스트.

router(pm2) 프로세스가 예전에 z.ai 모드였던 셸 env 를 그대로 물려받고
있으면, /open 이 항상 z.ai 로 라우팅되는 새 세션을 띄우는 문제가 있었다
(2026-07-04 발견). 기본은 z.ai 프록시 env 를 지운 Anthropic 공식,
`/open glm`(z.ai/zai 별칭)만 그 env 를 유지해 명시적으로 z.ai 를 쓴다.
그 외 인자(`/open opus` 등)는 Anthropic 공식 + `claude --model <인자>`.
"""
from imadhd.commands.base import Message
from imadhd.commands.open_command import (
    OpenCommand,
    build_open_env,
    parse_open_arg,
    _ANTHROPIC_PROXY_ENV_KEYS,
)


def _polluted_env():
    return {
        "HOME": "C:\\Users\\user",
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "secret-token",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.2",
    }


# ---------- match() ----------

def test_open_bare_still_matches():
    c = OpenCommand()
    assert c.match(Message("1", "/open", {}))


def test_open_glm_matches():
    c = OpenCommand()
    assert c.match(Message("1", "/open glm", {}))
    assert c.match(Message("1", "/open z.ai", {}))
    assert c.match(Message("1", "/open zai", {}))


def test_open_model_arg_matches():
    c = OpenCommand()
    assert c.match(Message("1", "/open sonnet", {}))
    assert c.match(Message("1", "/open opus", {}))
    assert c.match(Message("1", "/open claude-opus-4-8", {}))


def test_open_pure_digit_arg_does_not_match():
    """숫자 하나짜리 인자(/open 1)는 슬롯 선택 등 다른 명령과 헷갈릴 수 있어 제외."""
    c = OpenCommand()
    assert not c.match(Message("1", "/open 1", {}))


# ---------- parse_open_arg() ----------

def test_parse_open_arg_empty():
    assert parse_open_arg("") == (False, None)


def test_parse_open_arg_glm_alias():
    assert parse_open_arg("glm") == (True, None)
    assert parse_open_arg("z.ai") == (True, None)
    assert parse_open_arg("zai") == (True, None)


def test_parse_open_arg_model_name():
    assert parse_open_arg("sonnet") == (False, "sonnet")
    assert parse_open_arg("opus") == (False, "opus")


# ---------- build_open_env() ----------

def test_default_strips_zai_proxy_keys():
    env = build_open_env(_polluted_env(), use_glm=False)
    for k in _ANTHROPIC_PROXY_ENV_KEYS:
        assert k not in env
    assert env["HOME"] == "C:\\Users\\user"


def test_glm_keeps_proxy_keys():
    env = build_open_env(_polluted_env(), use_glm=True)
    assert env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-token"


def test_build_open_env_does_not_mutate_input():
    src = _polluted_env()
    build_open_env(src, use_glm=False)
    assert "ANTHROPIC_BASE_URL" in src  # 원본 os.environ 스타일 dict 는 건드리지 않음


# ---------- handle() — 실제 spawn 커맨드라인 검증 ----------

class _FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, **kw):
        self.sent.append(text)


def _handle_and_capture(monkeypatch, text):
    from imadhd.commands.base import CommandContext
    import imadhd.commands.open_command as oc

    # 이 테스트는 Windows 분기(subprocess.Popen)를 검증하는 테스트다.
    # os.name 분기가 생긴 뒤로는 실행 플랫폼이 posix면 else(tmux) 분기를
    # 타서 실제 tmux 명령이 호출되는 회귀가 있었다(2026-07-05 오라클에서
    # 발견 — 진짜 tmux new-session 이 시도됨). 플랫폼 무관하게 Windows
    # 분기를 테스트하도록 os.name 을 명시 고정한다.
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


def test_handle_model_arg_adds_model_flag(monkeypatch):
    captured, tg = _handle_and_capture(monkeypatch, "/open opus")
    # host.py 래핑(`py -m imadhd.host -- claude ...`)으로 Popen 마지막 인자는
    # 한 개의 inner cmdline 문자열. 모델 인자가 그 안에 claude tail 로 들어감.
    inner = captured["args"][-1]
    assert inner.endswith("claude --model opus")
    assert "imadhd.host" in inner
    assert "opus" in tg.sent[-1]


def test_handle_bare_open_no_model_flag(monkeypatch):
    captured, tg = _handle_and_capture(monkeypatch, "/open")
    inner = captured["args"][-1]
    assert inner.endswith("-- claude")
    assert "imadhd.host" in inner
    assert "--model" not in inner


def test_handle_glm_arg_no_model_flag(monkeypatch):
    captured, tg = _handle_and_capture(monkeypatch, "/open glm")
    inner = captured["args"][-1]
    assert inner.endswith("-- claude")
    assert "imadhd.host" in inner
    assert "GLM" in tg.sent[-1]
