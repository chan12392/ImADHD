"""ask_hook.router_alive 순수 로직 테스트.

router 가 좀비 상태(pm2 online 표시, 실제 폴링 정지)여도 heartbeat 파일
신선도로 감지해 280s 를 다 기다리지 않고 조기 timeout 하기 위한 판정 함수.
"""
import time

from imadhd.hooks.ask_hook import router_alive


def test_no_heartbeat_file_returns_true(tmp_path):
    """heartbeat 파일 자체가 없으면(구버전 router 등) 판단 보류 — 기존 동작 유지."""
    assert router_alive(tmp_path) is True


def test_fresh_heartbeat_is_alive(tmp_path):
    (tmp_path / "heartbeat.txt").write_text(str(time.time()), encoding="utf-8")
    assert router_alive(tmp_path, max_age=40.0) is True


def test_stale_heartbeat_is_dead(tmp_path):
    (tmp_path / "heartbeat.txt").write_text(str(time.time() - 100), encoding="utf-8")
    assert router_alive(tmp_path, max_age=40.0) is False


def test_corrupt_heartbeat_file_returns_true(tmp_path):
    """파싱 실패도 판단 보류(오탐으로 정상 대기를 끊지 않음)."""
    (tmp_path / "heartbeat.txt").write_text("garbage", encoding="utf-8")
    assert router_alive(tmp_path) is True
