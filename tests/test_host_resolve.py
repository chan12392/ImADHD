"""host._resolve_claude_exe / _resolve_child 단위테스트.

2026-07-06 실사고 회귀: host.py 가 npm shim(claude.CMD) 을 PTY 직자식으로
spawn → cmd.exe 종료 → PTY 닫힘 → claude.exe TTY 없이 고아화(transcript
0). 수리 = shim 역추적해 bin/claude.exe 직접 PTY 자식으로.
"""
import os

from imadhd.host import _resolve_child, _resolve_claude_exe


def _make_npm_tree(tmp_path):
    """tmp_path 밑에 npm global bin 구조 흉내. claude.exe 경로 반환."""
    npm_bin = tmp_path / "npm"
    pkg_bin = npm_bin / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    pkg_bin.mkdir(parents=True)
    exe = pkg_bin / "claude.exe"
    exe.write_bytes(b"fake-exe")
    shim = npm_bin / "claude.cmd"
    shim.write_text("fake shim")
    return str(exe), str(shim)


def test_resolve_claude_exe_direct(monkeypatch, tmp_path):
    exe, shim = _make_npm_tree(tmp_path)
    monkeypatch.setattr(
        "imadhd.host.shutil.which",
        lambda name: shim if name in ("claude", "claude.cmd") else None,
    )
    out = _resolve_claude_exe(["claude"])
    assert out is not None
    assert out[0] == exe  # bin/claude.exe 직접
    assert out[1:] == []


def test_resolve_claude_exe_passes_rest_args(monkeypatch, tmp_path):
    exe, shim = _make_npm_tree(tmp_path)
    monkeypatch.setattr(
        "imadhd.host.shutil.which",
        lambda name: shim if name in ("claude", "claude.cmd") else None,
    )
    out = _resolve_claude_exe(["claude", "--model", "opus"])
    assert out == [exe, "--model", "opus"]


def test_resolve_claude_exe_none_for_non_claude(monkeypatch):
    out = _resolve_claude_exe(["bash", "-lc", "echo hi"])
    assert out is None


def test_resolve_claude_exe_none_when_shim_missing(monkeypatch):
    monkeypatch.setattr("imadhd.host.shutil.which", lambda name: None)
    assert _resolve_claude_exe(["claude"]) is None


def test_resolve_claude_exe_none_when_pkg_bin_absent(monkeypatch, tmp_path):
    """shim 은 있으나 bin/claude.exe 없음(비표준 설치) → 폴백 유도 위해 None."""
    npm_bin = tmp_path / "npm"
    npm_bin.mkdir(parents=True)
    shim = npm_bin / "claude.cmd"
    shim.write_text("fake")
    monkeypatch.setattr("imadhd.host.shutil.which", lambda name: str(shim))
    assert _resolve_claude_exe(["claude"]) is None


def test_resolve_child_uses_direct_exe(monkeypatch, tmp_path):
    """_resolve_child 가 직접 exe 경로로 가는지(cmd.exe /c 폴백 타지 않는지)."""
    exe, shim = _make_npm_tree(tmp_path)
    monkeypatch.setattr(
        "imadhd.host.shutil.which",
        lambda name: shim if name in ("claude", "claude.cmd") else None,
    )
    out = _resolve_child(["claude"])
    assert out == [exe]
    assert "cmd.exe" not in out


def test_resolve_child_falls_back_to_cmd_for_other_shims(monkeypatch, tmp_path):
    """claude 아닌 다른 .cmd shim 은 기존 cmd.exe /c 폴백 유지(회귀 없음)."""
    fake_cmd = tmp_path / "tool.cmd"
    fake_cmd.write_text("fake")
    monkeypatch.setattr("imadhd.host.shutil.which", lambda name: str(fake_cmd))
    out = _resolve_child(["tool"])
    assert out[0].lower() == "cmd.exe"
    assert out[1] == "/c"
    assert out[2] == str(fake_cmd)


def test_resolve_child_empty_defaults_claude(monkeypatch, tmp_path):
    """빈 argv → default ['claude'](직접해석 안 함). main()은 parse_args 가
    항상 ['claude'] 를 세팅하므로 실제론 그 이후 단계에서 direct 해석 탄다."""
    _make_npm_tree(tmp_path)
    monkeypatch.setattr("imadhd.host.shutil.which", lambda name: None)
    assert _resolve_child([]) == ["claude"]
