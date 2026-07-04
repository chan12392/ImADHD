"""classify_getupdates_error 순수 로직 테스트.

401/403(토큰 무효·봇 차단)은 무한 재시도해도 의미 없으므로 stop(프로세스
종료 → pm2 재시작 카운트로 가시화). 429는 Retry-After 존중. 그 외는
5초 대기 재시도(기존 동작 유지).
"""
import urllib.error

from imadhd.core.router import classify_getupdates_error


def _http_error(code, headers=None):
    return urllib.error.HTTPError(
        url="https://api.telegram.org/botX/getUpdates",
        code=code,
        msg="err",
        hdrs=headers or {},
        fp=None,
    )


def test_401_stops():
    action, wait = classify_getupdates_error(_http_error(401))
    assert action == "stop"


def test_403_stops():
    action, wait = classify_getupdates_error(_http_error(403))
    assert action == "stop"


def test_429_waits_retry_after_header():
    action, wait = classify_getupdates_error(_http_error(429, {"Retry-After": "12"}))
    assert action == "wait"
    assert wait == 12.0


def test_429_without_header_falls_back_to_5s():
    action, wait = classify_getupdates_error(_http_error(429))
    assert action == "wait"
    assert wait == 5.0


def test_other_http_error_waits_5s():
    action, wait = classify_getupdates_error(_http_error(500))
    assert action == "wait"
    assert wait == 5.0


def test_generic_exception_waits_5s():
    action, wait = classify_getupdates_error(TimeoutError("boom"))
    assert action == "wait"
    assert wait == 5.0
