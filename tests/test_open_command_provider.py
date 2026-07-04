"""/open provider 선택(Anthropic 공식 vs GLM(z.ai)) 회귀 테스트.

router(pm2) 프로세스가 예전에 z.ai 모드였던 셸 env 를 그대로 물려받고
있으면, /open 이 항상 z.ai 로 라우팅되는 새 세션을 띄우는 문제가 있었다
(2026-07-04 발견). 기본은 z.ai 프록시 env 를 지운 Anthropic 공식,
`/open glm`(z.ai/zai 별칭)만 그 env 를 유지해 명시적으로 z.ai 를 쓴다.
"""
from imadhd.commands.base import Message
from imadhd.commands.open_command import (
    OpenCommand,
    build_open_env,
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


def test_open_unknown_arg_does_not_match():
    """기존 설계 의도 유지: /open + 모르는 인자는 다른 명령과 충돌 방지 위해 no-match."""
    c = OpenCommand()
    assert not c.match(Message("1", "/open 1", {}))
    assert not c.match(Message("1", "/open sonnet", {}))


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
