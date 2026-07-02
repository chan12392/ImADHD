# ImADHD

> Control **multiple terminal sessions from one Telegram chat**.
> Each running terminal gets a number (1–6). Send a DM starting with a number emoji (`2️⃣ do the thing`) and it routes to terminal #2. The terminal's reply comes back prefixed with the same number.

Built for driving several **Claude Code** (or any interactive TUI) sessions remotely — keep terminals running on your desktop, issue work from your phone when you're out.

## Why "ImADHD"?
One brain, many terminals in flight at once. 🧠⚡

---

## Status
🚧 **Early development.** Private repo, public release planned.

## How it works
```
you (phone) ──DM "3️⃣ check logs"──▶ Telegram Bot
                                      │ getUpdates (long-poll)
                              ┌───────▼────────┐
                              │  btg-router    │  (pm2 daemon)
                              │  parse "3"     │
                              │  registry → #3 │
                              └───┬────────┬───┘
     inject (send_keys) ──────────┘        └──────────── reply (Bot API)
              │                                              ▲
        ┌─────▼─────┐                              ┌────────┴───────┐
        │ Terminal 3 │ ──types reply ending with──▶│ Stop hook      │
        │ (Claude)   │   "<marker>"                │ captures+routes│
        └────────────┘                              └────────────────┘
```

- **Terminals don't know about Telegram.** The router injects keystrokes; a hook captures the reply.
- Terminal ↔ number mapping is tracked in a runtime registry (HWND + session id), **not** by window title.

## Components
| Piece | Role |
|---|---|
| `core/router.py` | Telegram long-poll + routing loop |
| `core/registry.py` | number ↔ session (HWND/pid) mapping |
| `transports/` | **pluggable** terminal input (default: Windows send_keys) |
| `commands/` | **pluggable** Telegram commands (`3️⃣ ...`, `/list`) |
| `reply/` | **pluggable** reply capture strategy |
| `hooks/register_hook.py` | CC `SessionStart`: claim a number |
| `hooks/reply_hook.py` | CC `Stop`: capture + send reply |

## Install (dev)
```bash
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
pip install -e ".[dev]"
cp .env.example .env   # then fill TELEGRAM_BOT_TOKEN
```

## Configure Claude Code hooks
Add to `~/.claude/settings.json`:
```jsonc
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "btg-register" }] }],
    "Stop":        [{ "hooks": [{ "type": "command", "command": "btg-reply"    }] }]
  }
}
```

## Run the router
```bash
pm2 start "btg-router" --name imadhd
pm2 logs imadhd
```

## Extending
- **New input method** (tmux/pty): add `imadhd/transports/yourmethod.py` implementing `Transport.inject()`, register in config. Core untouched.
- **New command** (`/status`): add `imadhd/commands/status.py` implementing `Command`. Core untouched.
- **Other reply channel** (discord): mirror `reply/` + `telegram_api/`.

## Platform
Windows-first (send_keys via ctypes). Transport interface leaves Linux/mac open for future.

## License
MIT — see [LICENSE](LICENSE).
