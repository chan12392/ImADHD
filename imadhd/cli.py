"""CLI 진입점 (entry_points).

  btg-router   → router_main   (pm2 데몬)
  btg-register → register_main (CC SessionStart 훅)
  btg-reply    → reply_main    (CC Stop 훅)
  btg-ask      → ask_main      (CC PreToolUse 훅: AskUserQuestion → 텔레그램 버튼)
"""
from __future__ import annotations

import sys

# 윈도우 콘솔(cp949)에서 ✅❌ 등 이모지/한글 print 깨짐 방지.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


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


def ask_main() -> int:
    from .hooks import ask_hook
    return ask_hook.main()


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
        print(f"✅ 명령 메뉴 등록 완료 (slots=1~{max_slots}, /list /new /help /pin)")
        print("   등록됨: " + ", ".join("/" + c for c in cmds))
        return 0
    print(f"❌ {resp}")
    return 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "router"
    sys.exit({"router": router_main, "register": register_main, "reply": reply_main,
              "adhd": adhd_main}.get(cmd, router_main)())
