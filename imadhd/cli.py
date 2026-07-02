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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "router"
    sys.exit({"router": router_main, "register": register_main, "reply": reply_main}.get(cmd, router_main)())
