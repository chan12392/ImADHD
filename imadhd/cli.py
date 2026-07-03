"""CLI 진입점 (entry_points).

  btg-router   → router_main   (pm2 데몬)
  btg-register → register_main (CC SessionStart 훅)
  btg-reply    → reply_main    (CC Stop 훅)
"""
from __future__ import annotations

import sys


def router_main() -> int:
    from .config import Settings
    from .core import router
    s = Settings.load()
    router.run(s)
    return 0


def register_main() -> int:
    from .hooks import register_hook
    return register_hook.main()


def reply_main() -> int:
    from .hooks import reply_hook
    return reply_hook.main()


def adhd_main() -> int:
    """봇 명령 메뉴 등록(setMyCommands).

      python -m imadhd adhd <bot_token>   # 토큰 인자
      python -m imadhd adhd               # .env TELEGRAM_BOT_TOKEN 사용

    인자 평문 토큰 = shell history 에 남으니 .env 방식 권장.
    """
    import os
    from .setup_commands import register

    args = sys.argv[2:]  # argv[1] = "adhd"
    token = (args[0] if args else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        # .env 도 시도
        try:
            from .config import Settings
            token = Settings.load().bot_token
        except Exception:
            pass
    if not token:
        print("usage: python -m imadhd adhd <bot_token>  (또는 .env 의 TELEGRAM_BOT_TOKEN)")
        return 2
    max_slots = int(os.environ.get("IMADHD_MAX_SLOTS", "6"))
    try:
        resp = register(token, max_slots)
    except Exception as e:
        print(f"❌ setMyCommands 실패: {e}")
        return 1
    if resp.get("ok"):
        from .setup_commands import build_commands
        cmds = [c["command"] for c in build_commands(max_slots)]
        print(f"✅ 명령 메뉴 등록 완료 (slots=1~{max_slots}, /list)")
        print("   등록됨: " + ", ".join("/" + c for c in cmds))
        return 0
    print(f"❌ {resp}")
    return 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "router"
    sys.exit({"router": router_main, "register": register_main, "reply": reply_main,
              "adhd": adhd_main}.get(cmd, router_main)())
