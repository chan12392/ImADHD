# ImADHD

> A **numbered Telegram MUX** for driving many local terminal sessions from one chat.
> Each running terminal gets a number (1–6). Send a DM starting with a number emoji — `2️⃣ check the logs` — and it's injected into terminal #2. The terminal's reply comes back prefixed with the same number.

Built for **Claude Code** (and any interactive TUI). Keep several terminals running on your **Windows** desktop; issue work from your phone when you're away. Replies route back automatically via a `Stop` hook.

## Why another Telegram↔Claude tool?

Most existing bridges (`ccgram`, `ccc`, `ccbot`, …) wrap Claude Code inside a **`tmux`** session on a Linux/mac box. ImADHD takes a different cut:

| | tmux-based bridges | **ImADHD** |
|---|---|---|
| What it touches | spawns/owns a tmux session | **reuses terminals you already have open** |
| Input | tmux `send-keys` | native Windows `send_keys` (ctypes, no deps) |
| Multi-session | one chat ↔ one session, or `/command`s | **one chat, N numbered slots** (ReplyKeyboard status board) |
| Platform | Linux / macOS | **Windows-first** (Windows Terminal, ConPTY) |

If you live in Windows Terminal / a Stream Deck launcher and want to keep your existing Claude Code windows as-is — just reachable from your phone — ImADHD is built for that. For headless Unix setups, the tmux bridges are the better fit.

## Why "ImADHD"?
One brain, many terminals in flight at once. 🧠⚡

---

## Status
`v0.1.0` — early, Windows-only, **single-machine** (router + terminals on the same host). Linux/mac transport is a future extension, not yet shipped.

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
- Terminal ↔ number mapping is tracked in a runtime registry (**HWND + pid + session id**), **not** by window title — so a renamed/recreated window is rediscovered automatically.
- **One Claude Code session per Windows Terminal window.** Injection targets the window handle of a specific slot. Run each terminal in its **own** WT window — if you pack several CC sessions as tabs in one window they can't be told apart and every DM lands in whatever tab is active. (Tip: launch with `wt -w new …`, or set WT `"windowingBehavior": "new"`.)
- A **status board** (Telegram `ReplyKeyboard`) shows every slot at a glance: ⭕ idle / 📝 busy / ⏳ pending / ❌ dead.

## Components
| Piece | Role |
|---|---|
| `core/router.py` | Telegram long-poll + routing loop |
| `core/registry.py` | number ↔ session (HWND/pid) mapping |
| `core/proc_win.py` | Windows process / window discovery (incl. stale-HWND auto-recovery) |
| `transports/` | **pluggable** terminal input (default: Windows send_keys) |
| `commands/` | **pluggable** Telegram commands (`3️⃣ ...`, `/list`, `/new`, ...) |
| `boards/` | status board (pinned text + ReplyKeyboard) |
| `hooks/register_hook.py` | CC `SessionStart`: claim a number |
| `hooks/reply_hook.py` | CC `Stop`: capture + send reply |
| `hooks/ask_hook.py` | CC `PreToolUse`: route `AskUserQuestion` to Telegram **inline buttons** |

## Install

Requires **Python ≥ 3.9** and **Node.js** (for pm2) on Windows, and a Telegram bot token from [@BotFather](https://t.me/BotFather).

### One-line (recommended)

`scripts/install.ps1` does everything — prompts for your token & chat id if not passed, then auto-runs all four steps (idempotent, safe to re-run):

1. **pm2** install + reboot survival (`pm2-windows-startup` + a `resurrect.cmd` hardened to call Node by absolute path so it survives login, + a `schtasks` ONLOGON backup), then starts the router daemon.
2. **Telegram command menu** — *merged*, not overwritten: any existing bot commands are preserved, only colliding names are replaced.
3. **Claude Code hooks** — `SessionStart` / `Stop` / `PreToolUse(AskUserQuestion)` added to `~/.claude/settings.json` (idempotent — existing hooks untouched, your token/chat injected into `settings.json.env`).
4. **Telegram pin** — the status board is created and pinned on first run.

```powershell
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
./scripts/install.ps1
# or non-interactive:
./scripts/install.ps1 -Token 123:ABC -Chat 123456789
```

That's it — open a Claude Code window and the `SessionStart` hook claims a slot; send `1️⃣ ping [A.D.H.D]` from Telegram to drive terminal #1.

> Install asks for `TELEGRAM_ALLOWED_CHAT_ID` (your user id from [@userinfobot](https://t.me/userinfobot)) and refuses to proceed without it — a public bot token alone would let anyone drive your terminals, so it's enforced **fail-closed**.

### Manual (fallback / dev)

`pip install -e ".[dev]"` adds pytest/ruff. `.env.example` documents every variable if you prefer to configure by hand; the manual hook + pm2 steps are detailed below.

```bash
pip install -e .            # runtime deps (python-dotenv)
pip install -e ".[dev]"     # + test suite / linting
cp .env.example .env       # then fill in the values
```

## Configure

Edit `.env`:

| Variable | Required | What |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **yes** | token from @BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | **yes** | your Telegram user id — get it from [@userinfobot](https://t.me/userinfobot) |
| `IMADHD_MAX_SLOTS` | no | max numbered terminals (default `6`) |
| `IMADHD_DATA_DIR` | no | runtime data dir (default `~/.imadhd`) |
| `IMADHD_TRANSPORT` | no | input transport (default `sendkeys_win`) |
| `IMADHD_REPLY_MARKER` | no | trailing phrase CC prints to trigger a reply (default `[A.D.H.D]`) |
| `IMADHD_ALLOW_ANY_CHAT` | **no — dev only** | set `1` to accept any chat without an allow-list. **Never on a public bot.** |

> **🔒 `TELEGRAM_ALLOWED_CHAT_ID` is enforced fail-closed.** Anyone holding your bot token can otherwise drive your terminals, so the router **refuses to start** if this is unset. The `IMADHD_ALLOW_ANY_CHAT=1` escape hatch is for local testing only.

## Configure Claude Code hooks

> **One-line install already does this.** This section is for manual setup / reference only.

Add to `~/.claude/settings.json`:

```jsonc
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "btg-register" }] }],
    "Stop":        [{ "hooks": [{ "type": "command", "command": "btg-reply"    }] }],
    "PreToolUse":  [{ "matcher": "AskUserQuestion",
                      "hooks":  [{ "type": "command", "command": "btg-ask", "timeout": 300000 }] }]
  }
}
```

The **`PreToolUse` / `AskUserQuestion`** hook makes Claude Code's clarifying questions arrive as **Telegram inline buttons** instead of stalling in the terminal. Tap an option → the answer is fed back to Claude Code and work continues — no phone-to-terminal round-trip, no native prompt UI. If no answer arrives within the timeout, the question is denied with a reason (Claude Code can re-ask). The hook is a no-op fallback (native prompt shown) when `TELEGRAM_ALLOWED_CHAT_ID` isn't configured.

Then teach Claude Code to end replies with the marker (so the `Stop` hook can route them back), e.g. in your `CLAUDE.md`:
> When a request ends with `[A.D.H.D]`, reply tersely and print `[A.D.H.D]` as the final line.

## Run the router

> **One-line install already does this** (pm2 daemon + reboot survival). This section is for manual control / reference.

```bash
pm2 start "btg-router" --name imadhd
pm2 logs imadhd      # expect: "router start: slots=6 ..."
```

Open a Claude Code window — `SessionStart` claims a slot and the status board lights up `⭕`. Send `1️⃣ ping [A.D.H.D]` from Telegram to drive terminal #1.

## Platform

**Windows-only today.** Input is native `send_keys` via ctypes (no tmux/pty). The `Transport` interface (`transports/base.py`) is the extension point for a future Linux/mac implementation; none ships yet.

## Extending
- **New input method** (tmux/pty): add `imadhd/transports/yourmethod.py` implementing `Transport.inject()`. Core untouched.
- **New command** (`/status`): add `imadhd/commands/status.py` implementing `Command`. Core untouched.
- **Other reply channel** (Discord): mirror `boards/` + `telegram_api/`.

## License
MIT — see [LICENSE](LICENSE).
