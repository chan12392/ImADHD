"""dispatch_hook 라우팅 단위 테스트.

dispatch_hook.main() 은 stdin 파싱 후 tool_name 으로 ask_handle/perm_handle 분기.
ask/perm 본체(Settings/Telegram/폴링)는 각 훅 단위테스트 + 대표님 라이브 검증에
위임 — 여기선 라우팅 분기만 stub 으로 검증.
"""
import io
import json

from imadhd.hooks import dispatch_hook


def _feed(monkeypatch, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_routes_askuserquestion_to_ask(monkeypatch):
    called = {}

    def fake_ask(payload):
        called["ask"] = payload
        return 0

    monkeypatch.setattr("imadhd.hooks.ask_hook.handle", fake_ask)
    _feed(monkeypatch, {"tool_name": "AskUserQuestion", "tool_input": {}})
    assert dispatch_hook.main() == 0
    assert called.get("ask", {}).get("tool_name") == "AskUserQuestion"


def test_routes_bash_to_perm(monkeypatch):
    called = {}

    def fake_perm(payload):
        called["perm"] = payload
        return 0

    monkeypatch.setattr("imadhd.hooks.perm_hook.handle", fake_perm)
    _feed(monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert dispatch_hook.main() == 0
    assert called.get("perm", {}).get("tool_name") == "Bash"


def test_routes_write_and_edit_to_perm(monkeypatch):
    hit = []

    def fake_perm(payload):
        hit.append(payload["tool_name"])
        return 0

    monkeypatch.setattr("imadhd.hooks.perm_hook.handle", fake_perm)
    for tn in ("Write", "Edit"):
        _feed(monkeypatch, {"tool_name": tn, "tool_input": {}})
        dispatch_hook.main()
    assert hit == ["Write", "Edit"]


def test_other_tools_no_dispatch(monkeypatch):
    """matcher 외 도구(Read 등)는 ask/perm 어느 쪽도 부르지 않음."""
    def boom(*a, **k):  # 호출되면 즉시 실패
        raise AssertionError("should not dispatch")

    monkeypatch.setattr("imadhd.hooks.ask_hook.handle", boom)
    monkeypatch.setattr("imadhd.hooks.perm_hook.handle", boom)
    _feed(monkeypatch, {"tool_name": "Read", "tool_input": {}})
    assert dispatch_hook.main() == 0


def test_invalid_stdin_returns_zero(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    assert dispatch_hook.main() == 0
