# ImADHD

> **[English](README.md)** | **[한국어](README.ko.md)**

> A **numbered Telegram MUX** for driving many local terminal sessions from one chat.
> Each running terminal gets a number (1–N). Send a DM — `2️⃣ check the logs` — and it's injected into terminal #2. The terminal's reply comes back prefixed with the same number.

Built for **Claude Code** (and any interactive TUI). Keep several terminals running on your **Windows** desktop or **Linux** server; issue work from your phone when you're away. Replies route back automatically via a `Stop` hook.

- **Windows** — **focus-less named-pipe injection** (`pipe_win`, default): a small PTY-bridge (`host.py`) muxes your keyboard with a named pipe, so Telegram input reaches the terminal **without stealing focus**. Falls back to native `send_keys` (`sendkeys_win`) if no bridge is running.
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
`v0.3.5` — **cross-platform** (Windows `pipe_win` default + `sendkeys_win` fallback; Linux `tmux_linux`). Single-machine (router + terminals on the same host).

### What's new
- **`v0.3.5`** — **progress board**: each busy slot shows a live `🟡 N번 작업중 (Xs)` counter (1 s refresh, auto-deleted on idle; completion still arrives as a separate reply DM), sent **silently** so it doesn't play a notification sound. Plus `perm_hook` log/input hardening (sha256 fingerprint + `html.escape`) with no behavior change.
- **`v0.3.4`** — intermittent inject fix: `host.py` now writes the body as **8-char chunks at human-typing cadence** before the submit `Enter`, defeating Claude Code TUI's bracketed-paste detection that occasionally left mid-length messages stuck in the input box.
- **`v0.3.3`** — **function-button board** (tap `/list`, `/open`, `/close`, `/use`, `/update-adhd`, … instead of typing) + **inline slot picker** popup for `/close /stop /use /new` when ≥2 terminals are active (single active = one-tap run); `/close` now **closes the Windows Terminal tab**; `/update-adhd` shows current/latest version + CHANGELOG and asks **Yes/No** inline before applying.

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
       (pipe_win / send_keys / tmux)             ▲
              │                                  │  (pending flag set at inject
        ┌─────▼─────┐                            │   marks this as a Telegram turn)
        │ Terminal 3 │ ──CC replies──────────────┴─▶┌────────┬───────┐
        │ (Claude)   │                              │Stop hook│       │
        └────────────┘                              │only on  │       │
                                                    │Telegram │       │
                                                    │turn →   │       │
                                                    │send+map │       │
                                                    └────────┴───────┘
```

- **Terminals don't know about Telegram.** The router injects input; a `Stop` hook sends the reply back **only for Telegram-originated turns** (tracked via a pending flag), so work you type directly in the terminal stays in the terminal.
- Terminal ↔ number mapping is tracked in a runtime registry (**Windows**: HWND + pid + session id; **Linux**: tmux pane + pid + session id) — so a renamed/recreated window/pane is rediscovered automatically.
- **Windows:** one Claude Code session per Windows Terminal window. Run each terminal in its **own** WT window — tabs in one window can't be told apart. (Tip: `wt -w new …`, or WT `"windowingBehavior": "new"`.)
- **Linux:** each session gets its own tmux pane (captured at `SessionStart`), so a single tmux server hosts many sessions cleanly.
- A **status board** (Telegram `ReplyKeyboard`) shows every slot at a glance: ⭕ idle / 📝 busy / ⏳ pending / ❌ dead. On top of that, a **progress board** posts a silent `🟡 N번 작업중 (Xs)` counter per busy slot (1 s refresh, auto-deleted on idle) — toggle with `IMADHD_PROGRESS_BOARD=0`.

## Components
| Piece | Role |
|---|---|
| `core/router.py` | Telegram long-poll + routing loop |
| `core/registry.py` | number ↔ session mapping (HWND/pid on Windows, tmux_pane/pid on Linux) |
| `core/proc_win.py` | Windows process / window discovery (incl. stale-HWND auto-recovery) |
| `core/reply_map.py` | reply routing by `reply_to` / pending-target |
| `transports/` | **pluggable** terminal input — `pipe_win` (focus-less, Windows default), `sendkeys_win` (focus-stealing fallback), `tmux_linux` (Linux default) |
| `host.py` | Windows PTY-bridge for `pipe_win`: owns the ConPTY, muxes keyboard ∪ named pipe so Telegram input never steals focus |
| `commands/` | **pluggable** Telegram commands (`3️⃣ ...`, `/list`, `/new`, `/open`, `/close`, ...) |
| `boards/` | status board (pinned text + ReplyKeyboard) + progress board (per-slot `🟡 작업중` counter) |
| `hooks/register_hook.py` | CC `SessionStart`: claim a number |
| `hooks/reply_hook.py` | CC `Stop`: capture + send reply |
| `hooks/ask_hook.py` | CC `PreToolUse` (`AskUserQuestion`): route clarifying questions to Telegram **inline buttons** |
| `hooks/perm_hook.py` | CC `PreToolUse` (`Bash\|Write\|Edit`): route **risky tool calls** (rm / `git push` / kill / sudo / ...) to Telegram **Yes/No** — safe tools auto-allow with zero latency; timeout → deny |
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
3. **Claude Code hooks** — `SessionStart` / `Stop` / `PreToolUse(AskUserQuestion)` / `UserPromptSubmit` added to `~/.claude/settings.json` (idempotent; existing hooks untouched). Token/chat are written to `~/.imadhd/env` (0600), **not** `settings.json`'s global `env` — and any token previously injected there by an older install is migrated out.
4. **Telegram pin** — the status board is created and pinned on first run.

Flags: `--token`, `--chat`, `--max-slots N` (default 6), `--skip-pm2`, `--skip-pin`.

> Install asks for `TELEGRAM_ALLOWED_CHAT_ID` (your user id from [@userinfobot](https://t.me/userinfobot)) and refuses to proceed without it — a public bot token alone would let anyone drive your terminals, so it's enforced **fail-closed**.

### Uninstall

One line undoes everything install did — in reverse, surgically, and preserving your own customizations:

```bash
python -m imadhd uninstall          # confirmation prompt
python -m imadhd uninstall --yes    # non-interactive (automation)
python -m imadhd uninstall --skip-pm2
```

It removes, in order:
1. **pm2** ImADHD processes + `pm2 save` (Windows: the ONLOGON `schtasks` entry; Linux: you run `sudo pm2 unstartup systemd` — needs root, so it's advised not silent-skipped).
2. **Telegram command menu** — *surgical*: only ImADHD's command names are filtered out (both `default` and `all_private_chats` scopes); your own bot commands are preserved. Empty scope → `deleteMyCommands`.
3. **Claude Code hooks** — the 4 ImADHD hook groups are dropped from `~/.claude/settings.json`; your other hooks/settings are untouched. A **redacted** backup (`settings.json.bak-uninstall-<ts>`, mode 0600) is written first.
4. **Telegram pin** — `unpinChatMessage` + delete (best-effort).
5. **data_dir** (`~/.imadhd`, including the token `env`) — wiped.
6. **`repo/.env`** — only ImADHD keys removed; if nothing else remains the file is deleted, otherwise rewritten mode 0600.

The token is never printed or logged anywhere. Everything is idempotent — missing pieces are skipped. The repo directory and the pip package are left for you to remove (`rm -rf ImADHD && pip uninstall imadhd`).

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
This injects into terminal #3. The inject sets a **pending flag** for that session; when Claude Code finishes, the `Stop` hook sees the flag, captures the reply, and routes it back to your phone prefixed `3️⃣`. Replies over the hard length limit are bounced back once with a "keep it short" nudge. Work you type **directly** in the terminal has no pending flag, so it stays local — nothing leaks to Telegram.

### Commands
| Command | What it does |
|---|---|
| `3️⃣ <text>` / `3 <text>` | send `<text>` to terminal #3 (also sets it as pending target) |
| `/list` | show active terminals + slot status |
| `/new <N>` | reset terminal #N (`/clear`) for a fresh conversation — e.g. `/new 1` |
| `/open` | open a new terminal in the user's home directory (Windows: new WT window; Linux: new tmux session). Home-based so CC recognizes its existing project & resume sessions. |
| `/close <N>` | close terminal #N (Windows: terminates the whole WT tab tree) — e.g. `/close 1` |
| `/stop <N>` | send ESC to terminal #N to abort the current task |
| `/use <N>` | set terminal #N as the **sticky default** — bare messages (no number) then route there until changed. `/use off` clears it |
| `/pin` | refresh the pinned status board |
| `/help` | command help |
| `/doctor` | self-diagnostic — router heartbeat, slots, pin, hooks, pm2 status |
| `/update-adhd` | self-update — shows current vs latest version + latest CHANGELOG, asks **Yes/No** inline, then `git pull` → `pytest` → `pm2 restart` (refuses restart on test failure) |

> **Tip:** you rarely need to type these. The status board's `ReplyKeyboard` is **function-button-first** — tap `📋 /list`, `📂 /open`, `✖️ /close`, `🎯 /use`, `🔄 /update-adhd`, … directly. For `/close /stop /use /new`, tapping the button pops up an **inline slot picker** showing only active terminals (tap the number to run); if just one terminal is active it runs immediately, no picker.

### Status board (pinned)
The pinned message shows every slot: ⭕ idle / 📝 busy / ⏳ pending / ❌ dead. The `ReplyKeyboard` is **function-button-first** — four rows of command buttons (`📋 /list`, `📌 /pin`, `🆕 /new`, `📂 /open`, `✖️ /close`, `⏹ /stop`, `🎯 /use`, `❓ /help`, `🩺 /doctor`, `🔄 /update-adhd`) over a compact 1️⃣–6️⃣ number keypad for injecting messages. It auto-refreshes as slots change state.

> **Single-terminal shortcut:** if only one slot is active, you can skip the number — a bare message is injected into that terminal automatically.

### Images (bidirectional)
- **CC → Telegram**: when Claude Code's reply carries an image (a generated PNG, a screenshot it produced), it is sent to your phone as a photo via `sendPhoto` — hand-rolled `multipart/form-data` (no `requests`), right alongside the text reply. Multiple images in one reply are each sent as their own message.
- **Telegram → CC**: send a photo to the bot and the largest size is downloaded to `~/.imadhd/inbox/tg_<file_id>.jpg` (atomic write); the active CC slot receives `이미지 수신: <path>` and can `Read` the file at that path to analyze it.

## Configure

Edit `.env`:

| Variable | Required | What |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **yes** | token from @BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | **yes** | your Telegram user id — get it from [@userinfobot](https://t.me/userinfobot) |
| `IMADHD_MAX_SLOTS` | no | max numbered terminals (default `6`) |
| `IMADHD_DATA_DIR` | no | runtime data dir (default `~/.imadhd`) |
| `IMADHD_TRANSPORT` | no | input transport — `pipe_win` (Windows, focus-less, **recommended**), `sendkeys_win` (Windows, focus-stealing fallback), `tmux_linux` (Linux). The `.env` value is authoritative and overrides any ambient env var. |
| `IMADHD_REPLY_MARKER` | no | legacy auxiliary signal (default `[A.D.H.D]`). Reply routing is driven by the **pending flag** set at inject time, not by a marker in the prompt — this is only a fallback for older inject paths. |
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
                            "hooks":  [{ "type": "command", "command": "python -m imadhd.hooks.ask_hook", "timeout": 300000 }] },
                          { "matcher": "Bash|Write|Edit",
                            "hooks":  [{ "type": "command", "command": "python -m imadhd.hooks.perm_hook", "timeout": 300000 }] }]
  }
}
```

The **`PreToolUse` / `AskUserQuestion`** hook makes Claude Code's clarifying questions arrive as **Telegram inline buttons** instead of stalling in the terminal. Tap an option → the answer is fed back to Claude Code and work continues — no phone-to-terminal round-trip. If no answer arrives within the timeout, the question is denied (Claude Code can re-ask). The hook is a no-op fallback (native prompt shown) when `TELEGRAM_ALLOWED_CHAT_ID` isn't configured.

The **`PreToolUse` / `Bash|Write|Edit`** hook (`perm_hook`) routes **risky tool calls** — `rm`, `git push`, `kill`, `sudo`, `drop`, writes to protected dirs, etc. — to a Telegram **Yes/No** before Claude Code runs them. Safe tools (`ls`, `cat`, edits outside protected paths) are auto-allowed with zero added latency. The hook's `permissionDecision: deny` is honored **even under `bypassPermissions`** mode — the hook fires before the permission-mode check, so this is your last-line gate from your phone. Timeout → deny (fail-closed). Terminal-direct turns (no Telegram marker) are skipped so local work is never gated.

> **No `CLAUDE.md` rule needed.** Replies are routed by a **pending flag** set at inject time, not by a trailing marker Claude Code has to print. Claude Code stays fully unaware that a turn came from Telegram — no prompt suffix, no marker echo, no behavioral rule to forget.

## Run the router

> **One-line install already does this** (pm2 daemon + reboot survival). This section is for manual control / reference.

```bash
pm2 start "python -m imadhd.cli router" --name imadhd --cwd "$PWD"
pm2 logs imadhd      # expect: "router start: slots=6 ..."
```

## Platform notes

- **Windows** — `pipe_win` (default) routes Telegram input through a named pipe into a `host.py` PTY-bridge, so input lands in the terminal **without stealing window focus**. Open terminals with the bot's `/open` command so they're launched under `host.py` automatically. `sendkeys_win` is the legacy fallback: native `send_keys` via ctypes that forces the target to the foreground first — set `IMADHD_TRANSPORT=sendkeys_win` to opt in. For `sendkeys_win`, `IMADHD_INJECT_METHOD=paste` (clipboard+Ctrl+V, default) is far faster than per-character `type`.
- **Linux** — input is `tmux send-keys` into the pane captured at `SessionStart`. Each Claude Code session runs in its own tmux session/pane; the registry tracks `tmux_pane` to target the right one. Auto-detected when `IMADHD_TRANSPORT` is unset.

## Extending
- **New input method** (ssh / pty): add `imadhd/transports/yourmethod.py` implementing `Transport.inject()`. Core untouched.
- **New command** (`/status`): add `imadhd/commands/status.py` implementing `Command`, register in `setup_commands.build_commands`. Core untouched.
- **Other reply channel** (Discord): mirror `boards/` + `telegram_api/`.

## License
MIT — see [LICENSE](LICENSE).
