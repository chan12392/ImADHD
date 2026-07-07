# Changelog

## 0.3.8 — 2026-07-07
- **번호 없는 이미지 → 라우팅 팝업 확장** — 0.3.7의 "↘️ 어느 터미널로?" 팝업을 텍스트 본문뿐 아니라 **이미지**에도 적용. 활성 터미널이 2개+이고 sticky·pending·번호 접두 없이 이미지를 올리면, 종전엔 `_handle_photo`가 `num=None`로 주입을 스킵해 "전송 안 됨"으로 인식됐음. 이제 이미지는 inbox에 저장(백업 보존)한 뒤 "↘️ 이 이미지를 어느 터미널로?" 인라인 버튼 팝업 송신 → 탭 시 해당 슬롯으로 경로 주입. 활성 0이면 "열린 터미널 없음" 안내(이미지는 저장됨). 구현상 `route_pending` 스키마를 `tuple[body,ts]` → `dict{kind:text|photo, body, ts}`로 일반화(`r:` 콜백이 kind 무관하게 동일 주입).
- **검증**: pytest 381 passed.

## 0.3.7 — 2026-07-07
- **`/close` 다중·전체 종료** — `/close N` 단일 외에 `/close N M …`(공백 다중), `/close N,M,…`(콤마 다중, 띄어쓰기 혼합 OK), `/close all`(활성 슬롯 전체) 지원. 다중 종료 시 슬롯별 kill 후 결과를 한 건으로 요약 송신(스팸 방지). 중복 번호 자동 제거·순서 보존. 숫자 아닌 인자 → 사용법 안내. 단일 `/close N`은 기존 동작·메시지 그대로(`_close_single` 경로).
- **번호 없는 본문 → 라우팅 팝업** — 번호(이모지/`/N`)·sticky·pending 없이 온 본문이 타겟 불명(활성 0 또는 2+ 개)일 때 기존엔 silent drop. 이제 "↘️ 어느 터미널로 보낼까?" 인라인 버튼(활성 슬롯 번호) 팝업 송신 → 탭 시 해당 슬롯으로 본문 주입. 본문은 `route_pending`(chat→(body,ts), 10분 TTL)에 대기. 콜백 스킴 `r:<num>`. 활성 0이면 "열린 터미널 없음" 안내. 활성 1개면 종전대로 자동 주입(모호성 없음).
- **검증**: pytest 381 passed.

## 0.3.6 — 2026-07-07
- **PreToolUse 훅 병합 (5→4)** — `ask_hook`(`AskUserQuestion`)과 `perm_hook`(`Bash|Write|Edit`) 두 `PreToolUse` 엔트리 → 단일 `dispatch_hook` 엔트리(matcher `AskUserQuestion|Bash|Write|Edit`)로 병합. stdin 1회 파싱 후 `tool_name`으로 분기, 동작 변화 없음. `install` 재실행 시 기존 개별 엔트리를 자동 제거·마이그레이션(더블 발화 충돌 방지). `uninstall`·`/doctor` 동기화.
- **`/new`(`/clear`) 직후 첨부/회신 누락 수정** — `/clear`는 같은 claude.exe PID 안에서 새 transcript(=새 `session_id`)를 시작하지만 `SessionStart` 훅이 재발화하지 않아 registry 매핑이 stale id에 고정 → 역방향 회신(`reply_hook`)이 slot·marker 조회에 실패해 "전송 안 됨"으로 인식. `busy_hook`(`UserPromptSubmit`)가 new session_id를 가장 먼저 관측하므로 같은 cwd 슬롯을 찾아 session_id와 `marker_pending`을 new로 자가치유. 단일 CC 가정.
- **검증**: pytest 360 passed.

## 0.3.5 — 2026-07-07
- **Progress board (#43)** — while a slot is busy, the router shows a per-slot counter `🟡 N번 작업중 (Xs)`, refreshed every 1 s via `edit_message_text`; when the slot goes idle the counter is auto-deleted. Completion results are still delivered as a separate reply DM, so the counter only reflects "work in progress". Togglable via `IMADHD_PROGRESS_BOARD=0` (default on). Commit `aa7ba22`.
- **Silent progress messages (#44)** — the counter's initial `send` now uses `disable_notification=True`, so "working" pings arrive without a notification sound (`edit`/`delete` are silent by nature). The message itself still appears. Commit `4a4c48a`.
- **perm-hook hardening (no behavior change)** — debug log now records an input **sha256 fingerprint** (length + 12-hex digest) instead of the raw body, and the Telegram approval body is run through `html.escape` to prevent `parse_mode=HTML` breakage / injection. Send-failure stays fail-open; verdict logic unchanged. Commit `014d0af`.
- **Verification**: pytest 335 passed; live board behavior + silent send confirmed on respawned router.

## 0.3.4 — 2026-07-07
- **Intermittent inject fix (#38)** — `host.py` `_write_record` now writes the body as **8-char chunks with 15 ms sleep between** (human-typing cadence) before the standalone submit `\r`. Previous single bulk write tripped CC TUI bracketed-paste detection on mid-length bodies → trailing `\r` became a newline → text stuck in the input box ("가끔 주입 안됨"). Chunked write defeats paste detection. Verified live on respawned CC (1번 백호). Cost: ~200 ms per 100 chars.

## 0.3.3 — 2026-07-07
- **`/close` closes the WT tab (#42)** — `find_tab_root` (proc_win: walks the CC parent chain to the `WindowsTerminal.exe` direct child = tab-root `cmd.exe`) → `terminate_tree` kills the whole tab tree. Verified live: tab closes. Requires WT `closeOnExit: "always"` (default `"graceful"` treats `taskkill /F` as abnormal and keeps the tab).
- **Image+text inject (#39)** — `host.py` `_write_record` now writes the body and the submit `\r` as **separate PTY writes** with a sleep between, defeating CC TUI bracketed-paste detection (long bodies made the trailing `\r` a newline, leaving text in the input box). Verified live: image+caption injects.
- **`/update-adhd` 2-stage with inline Yes/No (#41)** — shows current/latest version + latest CHANGELOG section + inline Yes/No (`u:update:yes|no`); router `u:` callback runs the pull→pytest→detached restart on Yes.
- **Board redesign (#40 + plan)** — `pin_board` now function-button-first (4 rows: list/pin/new, open/close/stop, use/help, doctor/update-adhd) + number keypad (2 rows); `slot_picker` inline popup for `/close /stop /use /new` when active ≥2 (single active = immediate run); `normalize_command` strips leading emoji so `✖️ /close` matches. `/update` (CC version-up inject) dropped.
- **Helpers** — `label_command` (tab label), `core/transcript.py` (session-id locate).
- **Verification**: pytest 333 passed; live: #39 image inject OK, #42 `/close` tab OK.

## 0.3.2 — 2026-07-06
- **Telegram command bundle (F1, F3, F4)**:
  - `/update-adhd` — self-update: `git pull --ff-only` → `pytest` → detached delayed `pm2 restart` (3s grace, survives self-kill). Refuses restart on test failure. Commits `2a48b89`.
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
