"""/doctor 진단 명령: 라우터·레지스트리·핀·훅·pm2·봇 메뉴 상태를 ✅/⚠️/❌ 로 보고.

라우터 프로세스(관리자)가 호출 → 같은 머신 리소스 직접 검사.
각 항목은 독립 try 로 일부 실패해도 전체 보고는 발송(부분 보고 > 침묵).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .base import Command, Message, CommandContext, normalize_command

# install.py HOOK_DEFS 와 동일 (재설치 안내 메시지용으로만 사용).
# PreToolUse = 단일 dispatch_hook (ask+perm 병합, 2026-07-07).
EXPECTED_HOOKS = {
    "SessionStart": "register_hook",
    "Stop": "reply_hook",
    "PreToolUse": "dispatch_hook",
    "UserPromptSubmit": "busy_hook",
}


class DoctorCommand(Command):
    TRIGGERS = {"/doctor", "/진단", "/status"}

    def match(self, msg: Message) -> bool:
        return normalize_command(msg.text) in self.TRIGGERS

    def handle(self, msg: Message, ctx: CommandContext) -> None:
        s = ctx.settings
        lines = ["🔍 ImADHD 진단"]
        lines.append(self._check_heartbeat(s))
        lines.append(self._check_registry(ctx, s))
        lines.append(self._check_pin(s))
        lines.append(self._check_hooks())
        lines.append(self._check_pm2())
        lines.append(self._check_bot_menu(ctx))
        ctx.telegram.send(msg.chat_id, "\n".join(lines))

    # ---------- 개별 검사 ----------

    @staticmethod
    def _check_heartbeat(s) -> str:
        try:
            age = time.time() - Path(s.heartbeat_path).stat().st_mtime
        except Exception:
            return "❌ heartbeat 없음 — 라우터 미실행?"
        # 롱폴 주기(5s)+여유. 30s 초과 = 좀비/사망 의심.
        if age <= 30:
            return f"✅ 라우터 생존 (heartbeat {age:.1f}s 전)"
        return f"⚠️ 라우터 지연/사망 의심 (heartbeat {age:.0f}s 전)"

    @staticmethod
    def _check_registry(ctx, s) -> str:
        try:
            actives = ctx.registry.active()
        except Exception as e:
            return f"❌ 레지스트리 조회 실패: {e}"
        busy = sum(1 for i in actives if getattr(i, "status", "") == "busy")
        return f"✅ 슬롯 {len(actives)}/{getattr(s, 'max_slots', 6)} 활성 ({busy} 작업중)"

    @staticmethod
    def _check_pin(s) -> str:
        try:
            sid = Path(s.data_dir) / "pin_message_id.txt"
            has = sid.exists() and sid.read_text(encoding="utf-8").strip()
        except Exception:
            return "⚠️ 핀 상태 파일 확인 실패"
        return "✅ 핀 본문 존재" if has else "⚠️ 핀 본문 없음 (/pin 으로 생성)"

    @staticmethod
    def _check_hooks() -> str:
        sf = Path.home() / ".claude" / "settings.json"
        if not sf.exists():
            return "❌ ~/.claude/settings.json 없음"
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            return "❌ settings.json 파싱 실패"
        hooks = data.get("hooks", {})
        missing = []
        for ev, mod in EXPECTED_HOOKS.items():
            blob = json.dumps(hooks.get(ev, []), ensure_ascii=False)
            if mod not in blob:
                missing.append(ev)
        if not missing:
            return "✅ 훅 4/4 설치됨"
        return (
            f"❌ 훅 누락 {len(missing)}개: {', '.join(missing)} "
            f"(재설치: python -m imadhd.install)"
        )

    @staticmethod
    def _check_pm2() -> str:
        try:
            out = subprocess.run(
                ["pm2", "jlist"], capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            return "⚠️ pm2 미설치 (수동 기동 환경일 수 있음)"
        except Exception as e:
            return f"⚠️ pm2 조회 실패: {e}"
        if out.returncode != 0:
            return "⚠️ pm2 응답 오류"
        try:
            procs = json.loads(out.stdout)
        except Exception:
            return "⚠️ pm2 출력 파싱 실패"
        router = None
        for p in procs:
            name = (p.get("name") or "").lower()
            script = ((p.get("pm2_env") or {}).get("pm_exec_path") or "").lower()
            if "imadhd" in name or "imadhd" in script:
                router = p
                break
        if not router:
            return "⚠️ pm2 imadhd 프로세스 없음 (수동 기동?)"
        env = router.get("pm2_env") or {}
        name = router.get("name", "?")
        status = env.get("status", "?")
        autorestart = env.get("autorestart", False)
        mark = "✅" if status == "online" else "❌"
        return f"{mark} pm2 {name} status={status} autorestart={autorestart}"

    @staticmethod
    def _check_bot_menu(ctx) -> str:
        tg = ctx.telegram
        try:
            default = {c.get("command") for c in (tg.get_my_commands() or [])}
            private = {c.get("command") for c in
                       (tg.get_my_commands(scope={"type": "all_private_chats"}) or [])}
        except Exception as e:
            return f"⚠️ 봇 메뉴 조회 실패: {e}"
        d, p = "use" in default, "use" in private
        if d and p:
            return "✅ 봇 메뉴 default+private /use 포함"
        if d or p:
            return "⚠️ 봇 메뉴 /use 일부 scope만 — 재설치 권장"
        return "❌ 봇 메뉴 /use 없음 (python -m imadhd.setup_commands)"
