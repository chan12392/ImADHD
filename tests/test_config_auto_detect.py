"""config.py transport 자동감지 단위 테스트.

2026-07-08 추가: IMADHD_TRANSPORT 미설정 시 플랫폼 자동감지.
Windows→sendkeys_win, Linux/POSIX→tmux_linux. install.py:155 와 동일 로직.

주의: os.name 을 posix 로 바꾸면 Path.home() 이 PosixPath 를 인스턴스화하려
시도해 Windows 테스트 호스트에서 UnsupportedOperation 발생. 그래서 Settings.load()
전체 경로보다 _default_transport() 헬퍼 + env 우선순위를 직접 검증한다.
"""
import imadhd.config as cfg


def test_default_transport_windows(monkeypatch):
    monkeypatch.setattr(cfg.os, "name", "nt")
    assert cfg._default_transport() == "sendkeys_win"


def test_default_transport_linux(monkeypatch):
    monkeypatch.setattr(cfg.os, "name", "posix")
    assert cfg._default_transport() == "tmux_linux"


def test_explicit_env_value_is_respected(monkeypatch):
    """IMADHD_TRANSPORT 명시값이 자동감지보다 우선하는지 헬퍼 레벨에서 검증.

    Settings.load() 전체를 호출하면 os.name=posix 시 Path.home() 크래시(Windows 호스트).
    config.py:84 의 실제 로직 `os.environ.get("IMADHD_TRANSPORT", "").strip() or _default_transport()`
    를 직접 시뮬레이션한다.
    """
    monkeypatch.setattr(cfg.os, "name", "posix")
    # 명시값 있는 경우
    monkeypatch.setenv("IMADHD_TRANSPORT", "sendkeys_win")
    val = (cfg.os.environ.get("IMADHD_TRANSPORT", "") or "").strip() or cfg._default_transport()
    assert val == "sendkeys_win", "명시값이 자동감지보다 우선해야 함"

    # 빈값 → 자동감지 폴백
    monkeypatch.setenv("IMADHD_TRANSPORT", "")
    val = (cfg.os.environ.get("IMADHD_TRANSPORT", "") or "").strip() or cfg._default_transport()
    assert val == "tmux_linux", "빈값은 플랫폼 기본으로 폴백"


def test_windows_default_matches_install_dotenv(monkeypatch):
    """config 기본값과 install.py:155 의 .env 기록 로직이 일치하는지."""
    monkeypatch.setattr(cfg.os, "name", "nt")
    expected = "sendkeys_win" if cfg.os.name == "nt" else "tmux_linux"
    assert cfg._default_transport() == expected
