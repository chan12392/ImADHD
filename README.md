# ImADHD

> A **numbered Telegram MUX** for driving many local terminal sessions from one chat.
> Each running terminal gets a number (1–N). Send a DM — `2️⃣ check the logs` — and it's injected into terminal #2. The terminal's reply comes back prefixed with the same number.

Built for **Claude Code** (and any interactive TUI). Keep several terminals running on your **Windows** desktop or **Linux** server; issue work from your phone when you're away. Replies route back automatically via a `Stop` hook.

- **Windows** — native `send_keys` (ctypes, no deps) into Windows Terminal / ConPTY windows.
- **Linux** — `tmux send-keys` into per-session tmux panes (headless servers).

## Why another Telegram↔Claude tool?

Most existing bridges (`ccgram`, `ccc`, `ccbot`, …) wrap Claude Code inside a **single `tmux`** session on a Linux/mac box. ImADHD takes a different cut:

| | tmux-based bridges | **ImADHD** |
|---|---|---|
| What it touches | spawns/owns a tmux session | **reuses terminals you already have open** |
| Windows input | — | **native `send_keys` (ctypes)** |
| Linux input | tmux `send-keys` | tmux `send-keys` (per-pane) |
| Multi-session | one chat ↔ one session, or `/command`s | **one chat, N numbered slots** (status board) |
| Platform | Linux / macOS | **Windows + Linux** |

If you live in Windows Terminal / a Stream Deck launcher and want to keep your existing Claude Code windows as-is — just reachable from your phone — ImADHD is built for that. Headless Linux box? Same chat, tmux panes, same commands.

## Why "ImADHD"?
One brain, many terminals in flight at once. 🧠⚡

---

## Status
`v0.2.0` — **cross-platform** (Windows `sendkeys_win` + Linux `tmux_linux`). Single-machine (router + terminals on the same host).

## How it works
```
you (phone) ──DM "3️⃣ check logs"──▶ Telegram Bot
                                      │ getUpdates (long-poll)
                              ┌───────▼────────┐
                              │  router        │  (pm2 daemon)
                              │  parse "3"     │
                              │  registry → #3 │
                              └───┬────────┬───┘
     inject ─────────────────────┘        └──────────── reply (Bot API)
       (send_keys / tmux send-keys)              ▲
              │                                              │
        ┌─────▼─────┐                              ┌────────┴───────┐
        │ Terminal 3 │ ──types reply ending with──▶│ Stop hook      │
        │ (Claude)   │   "<marker>"                │ captures+routes│
        └────────────┘                              └────────────────┘
```

- **Terminals don't know about Telegram.** The router injects keystrokes; a hook captures the reply.
- Terminal ↔ number mapping is tracked in a runtime registry (**Windows**: HWND + pid + session id; **Linux**: tmux pane + pid + session id) — so a renamed/recreated window/pane is rediscovered automatically.
- **Windows:** one Claude Code session per Windows Terminal window. Run each terminal in its **own** WT window — tabs in one window can't be told apart. (Tip: `wt -w new …`, or WT `"windowingBehavior": "new"`.)
- **Linux:** each session gets its own tmux pane (captured at `SessionStart`), so a single tmux server hosts many sessions cleanly.
- A **status board** (Telegram `ReplyKeyboard`) shows every slot at a glance: ⭕ idle / 📝 busy / ⏳ pending / ❌ dead.

## Components
| Piece | Role |
|---|---|
| `core/router.py` | Telegram long-poll + routing loop |
| `core/registry.py` | number ↔ session mapping (HWND/pid on Windows, tmux_pane/pid on Linux) |
| `core/proc_win.py` | Windows process / window discovery (incl. stale-HWND auto-recovery) |
| `core/reply_map.py` | reply routing by `reply_to` / pending-target |
| `transports/` | **pluggable** terminal input — `sendkeys_win` (default on Windows), `tmux_linux` (default on Linux) |
| `commands/` | **pluggable** Telegram commands (`3️⃣ ...`, `/list`, `/new`, `/open`, `/close`, ...) |
| `boards/` | status board (pinned text + ReplyKeyboard) |
| `hooks/register_hook.py` | CC `SessionStart`: claim a number |
| `hooks/reply_hook.py` | CC `Stop`: capture + send reply |
| `hooks/ask_hook.py` | CC `PreToolUse`: route `AskUserQuestion` to Telegram **inline buttons** |
| `hooks/busy_hook.py` | CC `UserPromptSubmit`: mark slot busy |

## Install

Requires **Python ≥ 3.9**, **Node.js** (for pm2), and a Telegram bot token from [@BotFather](https://t.me/BotFather).

### One-line install (recommended)

Both platforms install everything — pm2 daemon + reboot survival, Telegram command menu, Claude Code hooks, and the initial pinned status board. Idempotent and safe to re-run.

**Windows** (PowerShell):
```powershell
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
pip install -e .
python -m imadhd install
# or non-interactive:
python -m imadhd install --token 123:ABC --chat <YOUR_CHAT_ID>
```

**Linux** (bash):
```bash
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
pip install -e .
python -m imadhd install
# non-interactive:
python -m imadhd install --token 123:ABC --chat <YOUR_CHAT_ID>
```

The installer runs four steps:
1. **pm2** install + reboot survival (Windows: `pm2-windows-startup` + hardened `resurrect.cmd` calling Node by absolute path, plus a `schtasks` ONLOGON backup; Linux: `pm2 startup systemd`), then starts the router daemon.
2. **Telegram command menu** — *merged*, not overwritten: existing bot commands preserved, only colliding names replaced.
3. **Claude Code hooks** — `SessionStart` / `Stop` / `PreToolUse(AskUserQuestion)` / `UserPromptSubmit` added to `~/.claude/settings.json` (idempotent; existing hooks untouched; token/chat injected into `settings.json.env`).
4. **Telegram pin** — the status board is created and pinned on first run.

Flags: `--token`, `--chat`, `--max-slots N` (default 6), `--skip-pm2`, `--skip-pin`.

> Install asks for `TELEGRAM_ALLOWED_CHAT_ID` (your user id from [@userinfobot](https://t.me/userinfobot)) and refuses to proceed without it — a public bot token alone would let anyone drive your terminals, so it's enforced **fail-closed**.

### Manual (fallback / dev)

```bash
pip install -e .            # runtime deps (python-dotenv)
pip install -e ".[dev]"     # + test suite / linting
cp .env.example .env       # then fill in the values
```

`.env.example` documents every variable; the manual hook + pm2 steps are detailed below.

## Usage

Open a Claude Code window (Windows) or `tmux` attach + run Claude Code (Linux). The `SessionStart` hook claims a slot and the status board lights up `⭕`. Then drive it from Telegram:

### Send a message to a terminal
Type the slot number then your message. Both work:
```
3️⃣ check the logs and summarize
3 check the logs and summarize
```
This injects into terminal #3. When Claude Code replies (ending with the marker), it comes back to your phone prefixed `3️⃣`.

### Commands
| Command | What it does |
|---|---|
| `3️⃣ <text>` / `3 <text>` | send `<text>` to terminal #3 (also sets it as pending target) |
| `/list` | show active terminals + slot status |
| `/new <N>` | reset terminal #N (`/clear`) for a fresh conversation — e.g. `/new 1` |
| `/open` | open a new terminal (Windows: new WT window; Linux: new tmux session) |
| `/open <model>` | open a new terminal running a specific model (e.g. `/open glm`, `/open opus`) |
| `/close <N>` | close terminal #N — e.g. `/close 1` |
| `/stop <N>` | send ESC to terminal #N to abort the current task |
| `/pin` | refresh the pinned status board |
| `/help` | command help |

### Status board (pinned)
The pinned message shows every slot: ⭕ idle / 📝 busy / ⏳ pending / ❌ dead. The `ReplyKeyboard` mirrors the slot numbers so you can tap instead of type. It auto-refreshes as slots change state.

> **Single-terminal shortcut:** if only one slot is active, you can skip the number — a bare message is injected into that terminal automatically.

## Configure

Edit `.env`:

| Variable | Required | What |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **yes** | token from @BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | **yes** | your Telegram user id — get it from [@userinfobot](https://t.me/userinfobot) |
| `IMADHD_MAX_SLOTS` | no | max numbered terminals (default `6`) |
| `IMADHD_DATA_DIR` | no | runtime data dir (default `~/.imadhd`) |
| `IMADHD_TRANSPORT` | no | input transport — `sendkeys_win` (Windows) or `tmux_linux` (Linux). Auto-detected if unset. |
| `IMADHD_REPLY_MARKER` | no | trailing phrase CC prints to trigger a reply (default `[A.D.H.D]`) |
| `IMADHD_INJECT_METHOD` | no | Windows only: `paste` (clipboard+Ctrl+V, fast, default) or `type` (per-char SendInput, legacy) |
| `IMADHD_SKIP_PERMS` | **no — dangerous** | Linux only: set `1` to launch Claude Code with `--dangerously-skip-permissions`. Off by default — only enable if you accept that a compromised Telegram token means arbitrary commands on the host. |
| `IMADHD_ALLOW_ANY_CHAT` | **no — dev only** | set `1` to accept any chat without an allow-list. **Never on a public bot.** |

> **🔒 `TELEGRAM_ALLOWED_CHAT_ID` is enforced fail-closed.** Anyone holding your bot token can otherwise drive your terminals, so the router **refuses to start** if this is unset. The `IMADHD_ALLOW_ANY_CHAT=1` escape hatch is for local testing only.

> **🔐 Secret storage.** The installer writes the bot token to two files, both locked to `0600` on Linux/macOS: `repo/.env` (router) and `~/.imadhd/env` (Claude Code hooks). The hooks load it from there via `config.Settings.load()` — **not** from `~/.claude/settings.json`'s global `env`, so the token doesn't leak into every Claude Code session and subprocess.

## Configure Claude Code hooks

> **One-line install already does this.** This section is for manual setup / reference only.

Add to `~/.claude/settings.json`:

```jsonc
{
  "hooks": {
    "SessionStart":      [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.register_hook" }] }],
    "Stop":              [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.reply_hook"    }] }],
    "UserPromptSubmit":  [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.busy_hook"     }] }],
    "PreToolUse":        [{ "matcher": "AskUserQuestion",
                            "hooks":  [{ "type": "command", "command": "python -m imadhd.hooks.ask_hook", "timeout": 300000 }] }]
  }
}
```

The **`PreToolUse` / `AskUserQuestion`** hook makes Claude Code's clarifying questions arrive as **Telegram inline buttons** instead of stalling in the terminal. Tap an option → the answer is fed back to Claude Code and work continues — no phone-to-terminal round-trip. If no answer arrives within the timeout, the question is denied (Claude Code can re-ask). The hook is a no-op fallback (native prompt shown) when `TELEGRAM_ALLOWED_CHAT_ID` isn't configured.

Then teach Claude Code to end replies with the marker (so the `Stop` hook can route them back), e.g. in your `CLAUDE.md`:
> When a request ends with `[A.D.H.D]`, reply tersely and print `[A.D.H.D]` as the final line.

## Run the router

> **One-line install already does this** (pm2 daemon + reboot survival). This section is for manual control / reference.

```bash
pm2 start "python -m imadhd.cli router" --name imadhd --cwd "$PWD"
pm2 logs imadhd      # expect: "router start: slots=6 ..."
```

## Platform notes

- **Windows** — input is native `send_keys` via ctypes (no tmux/pty). Default `IMADHD_INJECT_METHOD=paste` is ~77× faster than legacy per-character typing; set `IMADHD_INJECT_METHOD=type` to roll back.
- **Linux** — input is `tmux send-keys` into the pane captured at `SessionStart`. Each Claude Code session runs in its own tmux session/pane; the registry tracks `tmux_pane` to target the right one. Auto-detected when `IMADHD_TRANSPORT` is unset.

## Extending
- **New input method** (ssh / pty): add `imadhd/transports/yourmethod.py` implementing `Transport.inject()`. Core untouched.
- **New command** (`/status`): add `imadhd/commands/status.py` implementing `Command`, register in `setup_commands.build_commands`. Core untouched.
- **Other reply channel** (Discord): mirror `boards/` + `telegram_api/`.

## License
MIT — see [LICENSE](LICENSE).
