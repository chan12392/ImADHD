"""Windows named-pipe transport (포커스 탈취 없는 주입).

호스트(CC wrapper)가 세션별 named pipe 서버
`\\\\.\\pipe\\imadhd-slot-<N>` (N = slot number) 를 열어두면 그 파이프로
텍스트를 주입 — 포커스 강제 탈취 없이 CC REPL 에 도달.
파이프가 없으면(래핑 안 된 구세션/구버전 슬롯) 기존 SendKeysWinTransport
(포커스 강제) 로 폴백.

Windows 전용. 타 OS 에서는 미임포트(ImportError) — config 에서 다른 transport 선택.

Wire protocol (host pipe-server 와 쌍 — 반드시 일치):
  - pipe path  : \\\\.\\pipe\\imadhd-slot-<N>   (N = target["number"])
  - client     : UTF-8 bytes 로 payload + b"\\n"  한 번에 write 후 close
  - payload    : text 의 \\r / \\n 을 스페이스로 치환
                 (sendkeys_win `_paste_clipboard` 정책과 동일 —
                  CC 터미널에서 \\n=Enter(제출) 로 작동해 조기 submit 방지)
  - one connection per inject (open → write → close)
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .base import InjectResult, Transport
from .sendkeys_win import SendKeysWinTransport

kernel32 = ctypes.windll.kernel32

GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3

# INVALID_HANDLE_VALUE = (HANDLE)(-1). ctypes c_void_p restype 은
# 64-bit Python 에서 부호 없는 0xFFFFFFFFFFFFFFFF 로, 32-bit 에선 0xFFFFFFFF 로,
# 일부 빌드에선 signed -1 로 나타날 수 있어 세 가지 후보로 비교.
_INVALID_HANDLE_VALUES = (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,        # lpFileName
    wintypes.DWORD,          # dwDesiredAccess
    wintypes.DWORD,          # dwShareMode
    ctypes.c_void_p,         # lpSecurityAttributes
    wintypes.DWORD,          # dwCreationDisposition
    wintypes.DWORD,          # dwFlagsAndAttributes
    wintypes.HANDLE,         # hTemplateFile
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,                       # hFile
    wintypes.LPCVOID,                      # lpBuffer
    wintypes.DWORD,                        # nNumberOfBytesToWrite
    ctypes.POINTER(wintypes.DWORD),        # lpNumberOfBytesWritten
    ctypes.c_void_p,                       # lpOverlapped
]
kernel32.WriteFile.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel32.WaitNamedPipeW.restype = wintypes.BOOL


class PipeWinTransport(Transport):
    """Named pipe → CC wrapper 주입. 파이프 부재/실패 시 SendKeysWinTransport 폴백.

    is_alive/send_key 은 파이프 존재 여부와 무시하고 항상 sendkeys 위임 —
    파이프는 inject 시점에만 검사(라우터가 is_alive 를 sweep 용으로 자주 부름).
    """

    def __init__(self) -> None:
        # lazy: 인스턴스 1개만 생성해 재사용. ctypes/객체 수 최소화.
        self._fallback: SendKeysWinTransport | None = None

    def _get_fallback(self) -> SendKeysWinTransport:
        if self._fallback is None:
            self._fallback = SendKeysWinTransport()
        return self._fallback

    def _pipe_write(self, pipe_path: str, data: bytes) -> bool:
        """단일 pipe-client 헬퍼 (open → write → close).

        반환 True = bytes 가 모두 기록됨.
        반환 False = 파이프 없음 / open 실패 / write 실패 / timeout.
        예외를 던질 수도 있음 — 호출자(inject)에서 try/except 로 폴백 처리.

        이 메서드를 단일 진입점으로 둬서 테스트는 이것만 monkeypatch 하면 된다
        (ctypes 내부를 직접 만질 필요 없음).

        흐름:
          1. WaitNamedPipeW — 파이프 부재 시 즉시 FALSE (fail-fast 핵심).
             파이프는 있지만 인스턴스들이 busy 면 timeout(ms) 까지 대기.
          2. CreateFileW — 클라이언트 연결(open).
          3. WriteFile + CloseHandle — 기록 후 즉시 닫기 (1 inject = 1 conn).
        """
        # 1s upper bound — 느린/무응답 서버가 라우터 폴링을 블럭하지 않도록.
        # 파이프 자체가 없으면 여기서 즉시 FALSE (ERROR_FILE_NOT_FOUND 경로).
        try:
            if not kernel32.WaitNamedPipeW(pipe_path, 1000):
                return False
        except Exception:
            return False

        handle = kernel32.CreateFileW(
            pipe_path,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        # restype=c_void_p → NULL 은 None, INVALID_HANDLE_VALUE 는 정수.
        if not handle or handle in _INVALID_HANDLE_VALUES:
            return False

        try:
            buf = ctypes.create_string_buffer(data)
            written = wintypes.DWORD(0)
            ok = kernel32.WriteFile(handle, buf, len(data),
                                    ctypes.byref(written), None)
            if not ok or written.value != len(data):
                return False
            return True
        finally:
            kernel32.CloseHandle(handle)

    def inject(self, target: dict, text: str, background: bool = False) -> InjectResult:
        N = target.get("number")
        if N is None:
            # number 키 없음 = 래핑 안 된 구버전 슬롯. 바로 폴백.
            return self._fallback_inject(target, text, background)

        pipe_path = fr"\\.\pipe\imadhd-slot-{N}"
        # \n/\r → space (CC 터미널 조기 submit 방지. sendkeys 정책과 동일).
        payload = text.replace("\r", " ").replace("\n", " ")
        data = payload.encode("utf-8") + b"\n"

        try:
            if self._pipe_write(pipe_path, data):
                return InjectResult(
                    delivered=True,
                    method="pipe",
                    note="named pipe inject (no focus)",
                )
        except Exception:
            # _pipe_write 가 예외를 던지는 경우도 폴백으로 처리(robustness).
            pass

        # 파이프 실패(반환 False 또는 예외) → 포커스 폴백.
        return self._fallback_inject(target, text, background)

    def _fallback_inject(self, target: dict, text: str,
                         background: bool) -> InjectResult:
        """SendKeysWinTransport 위임. method 앞에 fallback: prefix 부여 —
        호출자(라우터/로그)가 '파이프 안 뚫렸다(저하 발생)' 를 볼 수 있게."""
        result = self._get_fallback().inject(target, text, background)
        return InjectResult(
            delivered=result.delivered,
            method=f"fallback:{result.method}",
            note=result.note,
            rediscovered_hwnd=result.rediscovered_hwnd,
        )

    def is_alive(self, target: dict) -> bool:
        """CC pid 생사만. 파이프 존재 여부는 inject 시점에만 검사한다.

        is_alive 는 라우터가 5~6s 마다 sweep_dead 용으로 자주 부르므로,
        매번 pipe open/close 하면 비용이 크고 빈 파이프 폴백 세션을
        오판할 수 있다. pid 기반 생사가 정확(sendkeys_win 구현 참조).
        """
        return bool(self._get_fallback().is_alive(target))

    def send_key(self, target: dict, vk: int) -> InjectResult:
        """PoC: /stop(ESC) 등 가상키 = 포커스 경로 위임.

        TODO(향후 작업): pipe 기반 제어 프로토콜(ESC 등 제어 신호) 정의 후
        _pipe_write 의 제어 채널로 전환. 현 host 파이프 서버는 텍스트 payload
        만 정의해 제어 신호는 미지원 — 인터페이스(TBD) 합의 후 추가.
        """
        return self._get_fallback().send_key(target, vk)
