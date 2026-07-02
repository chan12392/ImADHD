# Changelog

## 0.2.0 — 2026-07-03
- Full implementation (T1–T9): registry, telegram client, send_keys transport, SessionStart/Stop hooks, inject/list commands, router long-poll loop.
- 29 unit tests passing (registry, number alloc, parsing, inject logic, marker capture).
- Live integration: CC hooks registered (`~/.claude/settings.json`), pm2 router daemon (`imadhd`), bot token via env/.env (never committed).
- Telegram bot `@chloe_desk_bot` polls getUpdates; DMs prefixed with number emoji (1️⃣–6️⃣) inject into the matching terminal; replies ending in marker are routed back prefixed with the number emoji.
- **E2E verified (2026-07-03)**: router long-poll, SessionStart number assignment (3 slots live), send_keys injection + ack, marker → Stop hook → reply round-trip all confirmed live.

## 0.1.0 — 2026-07-02
- Initial scaffold: package layout, ABC interfaces (Transport / Command / ReplyStrategy), config loader, CLI entry points.
- Implementation pending (see docs/design.md).
