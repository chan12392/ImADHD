# Changelog

## 0.3.2 — 2026-07-06
- **Telegram command bundle (F1–F4)**:
  - `/update-adhd` — self-update: `git pull --ff-only` → `pytest` → detached delayed `pm2 restart` (3s grace, survives self-kill). Refuses restart on test failure. Commits `2a48b89`.
  - `/update` — injects `!claude update` into the active CC slot (reuses `inject_command.do_inject`). Commit `2a48b89`.
  - **Tool-permission gate** (`perm_hook`, PreToolUse `Bash|Write|Edit`) — risky tools (rm/push/kill/sudo/drop/...) routed to Telegram Yes/No inline buttons; safe tools auto-allow with zero latency. `deny` is enforced even under `bypassPermissions` (hook fires before permission-mode check). Timeout → deny. Commits `2a48b89` + live verify.
  - **Bidirectional images** — CC→TG: assistant `image` blocks (Anthropic SDK base64) decoded and sent via `sendPhoto` (hand-rolled multipart, **0 deps**). TG→CC: incoming photos downloaded to `~/.imadhd/inbox/` and the path injected into the active CC. Commits `2a48b89` (TG→CC) + `fa499a7` (CC→TG).
- **Stability**: pipe-restore B root-cause — slot-based → **host_pid-based** matching (`b6b3cda`); `/open` simplification + `core/io_utils.py` atomic-write module (`f2fc24e`); pm2-zombie `boot_check` first-line defense (`972be2d`); `sync_alive` registry self-heal (`1125c87`).
- **Security**: install scrubber now covers unquoted + dotenv secret values (P3 closed, `59022c5`). Full leak scan (token + chat-id) clean across commits.
- **Verification**: pytest 308 passed; live E2E (perm `allow` emit, `send_photo ok`, inbox 35 KB JPEG); reboot round-trip confirmed.

## 0.3.1 — 2026-07-06
- **pipe_win default** — focus-less named-pipe injection via a ConPTY bridge (`host.py`); `sendkeys_win` kept as fallback. Commits `7472b75`, `21f80b0`.
- **Reply model overhaul** — marker dependency removed; replies now gated on a **pending flag** set at inject time + length gate. Claude Code is fully unaware a turn originated from Telegram (no `CLAUDE.md` rule, no prompt marker). Commit `b80c890`.
- **`/open` host wrapping** — opens pipe-capable terminals under `host.py`. Commit `a4d96f4`.
- **`.env` authority** — `Settings.load()` overrides ambient env (incident: a session-level `IMADHD_TRANSPORT=sendkeys_win` survived nowhere on disk but lived in the process tree). Commit `56cf4e3`.

## 0.3.0 — 2026-07-06
- **Sticky target `/use <N>`** — TTL-less default slot; bare messages route to the sticky target. `🎯` marker on the board.
- **Chunk reply routing** — `send()` returns all message_ids; every chunk mapped in `reply_map` so a reply to any chunk routes correctly.
- **`/doctor`** — self-diagnostic (router heartbeat, slots, pin, hooks, pm2, bot-menu scopes).
- **Public-release security hardening (5 rounds, P1×2 + P2×5 + P3×5)** — shell-injection allowlist + `shlex.quote`, token migrated out of `settings.json` global `env` into `~/.imadhd/env` (0600), scrubbed + atomic backups, clipboard clear. Commits `d5b3ca9`…`59022c5`.
- **One-line uninstall** — `python -m imadhd uninstall` mirrors install (surgical, idempotent, redacted 0600 backup).

## 0.2.0 — 2026-07-03
- Full implementation (T1–T9): registry, telegram client, send_keys transport, SessionStart/Stop hooks, inject/list commands, router long-poll loop.
- 29 unit tests passing (registry, number alloc, parsing, inject logic, marker capture).
- Live integration: CC hooks registered (`~/.claude/settings.json`), pm2 router daemon (`imadhd`), bot token via env/.env (never committed).
- Telegram bot `@claude_code_bot` polls getUpdates; DMs prefixed with number emoji (1️⃣–6️⃣) inject into the matching terminal; replies ending in marker are routed back prefixed with the number emoji.
- **E2E verified (2026-07-03)**: router long-poll, SessionStart number assignment (3 slots live), send_keys injection + ack, marker → Stop hook → reply round-trip all confirmed live.

## 0.1.0 — 2026-07-02
- Initial scaffold: package layout, ABC interfaces (Transport / Command / ReplyStrategy), config loader, CLI entry points.
- Implementation pending (see docs/design.md).
