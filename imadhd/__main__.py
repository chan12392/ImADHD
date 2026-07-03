"""python -m imadhd <subcommand> 진입.

  router    pm2 라우터 데몬 (기본)
  register  CC SessionStart 훅
  reply     CC Stop 훅
  adhd      봇 명령 메뉴 자동 등록 (setup)
"""
import sys

from .cli import router_main, register_main, reply_main, adhd_main

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "router"
    sys.exit({"router": router_main, "register": register_main, "reply": reply_main,
              "adhd": adhd_main}.get(cmd, router_main)())
