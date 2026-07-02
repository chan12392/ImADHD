"""슬롯 생사 진단: registry 각 슬롯의 hwnd/pid 실제 상태 + CC transcript 존재."""
from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def hwnd_info(hwnd):
    if not hwnd:
        return "hwnd=0"
    alive = bool(user32.IsWindow(hwnd))
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return f"IsWindow={alive} pid={pid.value} title={buf.value!r}"


def proc_name(pid):
    if not pid:
        return "?"
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid}).ProcessName"],
            text=True, creationflags=0x08000000).strip()
        return out
    except Exception as e:
        return f"err:{e}"


def main():
    reg_path = Path.home() / ".imadhd" / "registry.json"
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    # 실제 프로세스 스냅
    try:
        import subprocess
        ps = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process WindowsTerminal,claude,node -ErrorAction SilentlyContinue | "
             "Select-Object Id,ProcessName | ConvertTo-Csv -NoTypeInformation"],
            text=True, creationflags=0x08000000).strip()
    except Exception as e:
        ps = f"err:{e}"
    print("=== live procs ===")
    print(ps)
    print("=== slots ===")
    for k, v in data.items():
        if not v:
            print(f"slot {k}: empty")
            continue
        print(f"slot {k}: num={v['number']} sess={v['session_id'][:8]} "
              f"pid={v['pid']} proc={proc_name(v['pid'])} cwd={v['cwd']}")
        print(f"        hwnd={v['hwnd']} -> {hwnd_info(v['hwnd'])}")
        # CC transcript 존재?
        # ~/.claude/projects/<escaped-cwd>/<session>.jsonl
        proj = str(Path(v["cwd"]).resolve()).replace("\\", "/")
        # CC 경로 이스케이프 규칙 대략
        esc = proj.replace(":", "-").replace("/", "-")
        cand = Path.home() / ".claude" / "projects" / esc / f"{v['session_id']}.jsonl"
        alt = Path.home() / ".claude" / "projects" / esc.replace("-", "-") / f"{v['session_id']}.jsonl"
        found = cand.exists() or alt.exists()
        print(f"        transcript exists={found} ({cand.name})")


if __name__ == "__main__":
    main()
