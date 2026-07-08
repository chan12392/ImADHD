# ImADHD

> **[English](README.md)** | **[한국어](README.ko.md)**

> 하나의 채팅에서 여러 로컬 터미널 세션을 구동하는 **번호付き Telegram MUX**.
> 각 실행 중인 터미널에 번호(1–N)가 부여됩니다. DM으로 `2️⃣ 로그 확인해` 보내면 2번 터미널에 주입되고, 그 터미널의 답장은 같은 번호와 함께 돌아옵니다.

**Claude Code**(및 모든 인터랙티브 TUI)를 위해 만들었습니다. **Windows** 데스크톱이나 **Linux** 서버에 여러 터미널을 띄워 두고, 자리 비운 사이 폰에서 작업을 지시하세요. 답장은 `Stop` 훅이 자동으로 라우팅합니다.

- **Windows** — **포커스를 빼앗지 않는 named-pipe 주입**(`pipe_win`, 기본값): 작은 PTY-bridge(`host.py`)가 키보드와 named pipe를 멀티플렉싱하여, Telegram 입력이 터미널에 도달할 때 **포커스를 훔치지 않습니다**. bridge가 없으면 네이티브 `send_keys`(`sendkeys_win`)로 폴백합니다.
- **Linux** — 세션별 tmux pane으로 `tmux send-keys`(헤드리스 서버).

## 왜 또 다른 Telegram↔Claude 도구인가요?

기존 대부분의 bridge(`ccgram`, `ccc`, `ccbot`, …)는 Claude Code를 Linux/mac 머신의 **단일 `tmux` 세션** 안에 감쌉니다. ImADHD는 다른 각도에서 접근합니다:

| | tmux 기반 bridge | **ImADHD** |
|---|---|---|
| 건드리는 대상 | tmux 세션을 직접 생성/소유 | **이미 열려있는 터미널을 재사용** |
| Windows 입력 | — | **네이티브 `send_keys` (ctypes)** |
| Linux 입력 | tmux `send-keys` | tmux `send-keys` (pane별) |
| 다중 세션 | 한 채팅 ↔ 한 세션, 또는 `/command` | **한 채팅, N개 번호 슬롯**(상태 보드) |
| 플랫폼 | Linux / macOS | **Windows + Linux** |

Windows Terminal이나 Stream Deck 런처를 쓰면서 기존 Claude Code 창을 그대로 둔 채 — 폰에서만 접근 가능하게 — 만들고 싶다면 ImADHD가 그 목적입니다. 헤드리스 Linux 박스라도 같은 채팅, tmux pane, 같은 명령.

## 왜 이름이 "ImADHD"인가요?
하나의 뇌, 동시에 떠 있는 여러 터미널. 🧠⚡

---

## 상태
`v0.3.7` — **크로스플랫폼**(Windows `pipe_win` 기본 + `sendkeys_win` 폴백, Linux `tmux_linux`). 단일 머신(라우터와 터미널이 같은 호스트).

### 새 소식
- **`v0.3.7`** — **`/close` 다중·전체 종료**: 기존 단일 `/close N`에 더해 `/close N M …`(공백 다중), `/close N,M,…`(콤마 다중, 띄어쓰기 혼합 OK), `/close all`(활성 슬롯 전체) 지원. 다중 종료는 슬롯별 kill 후 결과를 한 줄로 요약 송신(스팸 방지), 중복 번호 자동 제거. **번호 없는 본문 라우팅 팝업**: 번호/sticky/pending 없이 온 본문이 타겟 불명(활성 0 또는 2+ 개)일 때 기존엔 조용히 사라졌는데, 이제 "↘️ 어느 터미널로 보낼까?" 인라인 버튼이 팝업 → 탭하면 해당 슬롯으로 주입(본문 10분 TTL 대기). 활성 1개면 종전대로 자동 주입.
- **`v0.3.6`** — **PreToolUse 훅 통합(5→4)**: 두 `PreToolUse` 엔트리(`AskUserQuestion`용 `ask_hook`, `Bash|Write|Edit`용 `perm_hook`) → stdin을 1회만 파싱하고 `tool_name`으로 분기하는 단일 `dispatch_hook` 엔트리로 병합. 동작 변화 없음. `install` 재실행 시 기존 설치를 자동 마이그레이션(더블 발화 충돌 방지용 레거시 개별 엔트리 스크럽). **`/new`(`/clear`) 직후 회신/첨부 누락 수정**: `/clear` 직후 CC `session_id`가 바뀌지만 `SessionStart` 훅은 재발화하지 않아 registry 매핑이 stale id에 고정 → 역방향 회신(`reply_hook`)이 누락되어("이미지가 안 보내져") 인식됨. `busy_hook`(`UserPromptSubmit`)가 new `session_id`를 가장 먼저 관측하므로, `cwd` 매칭으로 슬롯 매핑 + `marker_pending`을 자가치유하도록 수정.
- **`v0.3.5`** — **진행 보드**: 작업중인 슬롯마다 실시간 `🟡 N번 작업중 (Xs)` 카운터(1초 갱신, idle 전환 시 자동 삭제; 완료 결과는 별도 답장 DM으로 그대로 도착)를 **무음(silent)**으로 게시합니다. 더해 `perm_hook` 로그/입력 강화(sha256 지문 + `html.escape`, 동작 변화 없음).
- **`v0.3.4`** — 간헐적 주입 실패 수정: `host.py`가 본문을 이제 **8자 청크로 사람 타이핑 속도**로 쓴 뒤 제출 `Enter`를 보냅니다. 이전의 통째 쓰기는 Claude Code TUI의 bracketed-paste 감지에 걸려, 중간 길이 메시지가 가끔 입력창에만 남는 문제를 해결합니다.
- **`v0.3.3`** — **기능버튼 보드**(`/list`, `/open`, `/close`, `/use`, `/update-adhd`, … 를 타이핑 대신 탭) + 활성 터미널이 2개 이상일 때 `/close /stop /use /new`용 **인라인 slot picker** 팝업(단일 활성 = 한 번 탭에 즉시 실행); `/close`가 이제 **Windows Terminal 탭을 닫습니다**; `/update-adhd`는 현재/최신 버전과 CHANGELOG를 보여주고 적용 전 **예/아니오** 인라인 확인.

## 동작 방식
```
you (phone) ──DM "3️⃣ 로그 확인"──▶ Telegram Bot
                                      │ getUpdates (long-poll)
                              ┌───────▼────────┐
                              │  router        │  (pm2 daemon)
                              │  "3" 파싱       │
                              │  registry → #3 │
                              └───┬────────┬───┘
     inject ─────────────────────┘        └──────────── reply (Bot API)
       (pipe_win / send_keys / tmux)             ▲
              │                                  │  (주입 시점에 pending 플래그
        ┌─────▼─────┐                            │   설정 = 이 턴이 Telegram 턴임)
        │ Terminal 3 │ ──CC 답장──────────────────┴─▶┌────────┬───────┐
        │ (Claude)   │                              │Stop hook│       │
        └────────────┘                              │Telegram │       │
                                                    │턴일 때만│       │
                                                    │ send+map│       │
                                                    └────────┴───────┘
```

- **터미널은 Telegram을 모릅니다.** 라우터가 입력을 주입하고 `Stop` 훅이 답장을 **Telegram에서 시작된 턴에만**(pending 플래그로 추적) 보내므로, 터미널에 직접 타이핑한 작업은 터미널 안에만 머뭅니다.
- 터미널↔번호 매핑은 런타임 레지스트리가 추적합니다(**Windows**: HWND + pid + session id, **Linux**: tmux pane + pid + session id). 이름이 바뀌거나 재생성된 창/pane도 자동으로 재발견됩니다.
- **Windows:** Windows Terminal 창 하나당 Claude Code 세션 하나. 각 터미널은 **자기만의** WT 창에서 실행하세요 — 한 창의 탭은 서로 구분할 수 없습니다. (팁: `wt -w new …`, 또는 WT `"windowingBehavior": "new"`.)
- **Linux:** 각 세션이 자기만의 tmux pane(`SessionStart`에서 캡처)을 가져, 단일 tmux 서버가 여러 세션을 깔끔하게 호스팅합니다.
- **상태 보드**(Telegram `ReplyKeyboard`)가 모든 슬롯을 한눈에: ⭕ 대기 / 📝 작업중 / ⏳ 대기중 / ❌ 죽음. 그 위에 **진행 보드**가 작업중 슬롯마다 무음 `🟡 N번 작업중 (Xs)` 카운터(1초 갱신, idle 시 자동 삭제)를 게시합니다 — `IMADHD_PROGRESS_BOARD=0`으로 끌 수 있습니다.

## 컴포넌트
| 구성 | 역할 |
|---|---|
| `core/router.py` | Telegram long-poll + 라우팅 루프 |
| `core/registry.py` | 번호 ↔ 세션 매핑(Windows: HWND/pid, Linux: tmux_pane/pid) |
| `core/proc_win.py` | Windows 프로세스/창 탐색(오래된 HWND 자동 복구 포함) |
| `core/reply_map.py` | `reply_to` / pending-target 기반 답장 라우팅 |
| `transports/` | **플러그형** 터미널 입력 — `pipe_win`(포커스 无, Windows 기본), `sendkeys_win`(포커스 강탈 폴백), `tmux_linux`(Linux 기본) |
| `host.py` | `pipe_win`용 Windows PTY-bridge: ConPTY 소유, 키보드 ∪ named pipe 멀티플렉스 → Telegram 입력이 포커스를 뺏지 않음 |
| `commands/` | **플러그형** Telegram 명령(`3️⃣ ...`, `/list`, `/new`, `/open`, `/close`, ...) |
| `boards/` | 상태 보드(고정 텍스트 + ReplyKeyboard) + 진행 보드(슬롯별 `🟡 작업중` 카운터) |
| `hooks/register_hook.py` | CC `SessionStart`: 번호 할당 |
| `hooks/reply_hook.py` | CC `Stop`: 답장 캡처 + 전송 |
| `hooks/dispatch_hook.py` | CC `PreToolUse`(`AskUserQuestion\|Bash\|Write\|Edit`): **단일 진입점** — `tool_name`으로 `ask_hook`(명확화 질문 → 인라인 버튼) 또는 `perm_hook`(위험 도구 → 예/아니오)로 분기. 기존 2개 엔트리를 병합(훅 5→4, 동작 변화 없음) |
| `hooks/ask_hook.py` | `AskUserQuestion` 로직(`dispatch_hook`이 호출): 인라인 버튼 라우팅 |
| `hooks/perm_hook.py` | `Bash\|Write\|Edit` 로직(`dispatch_hook`이 호출): 위험 도구 예/아니오 게이트 — 안전 도구 자동 허용, 타임아웃 → 거부 |
| `hooks/busy_hook.py` | CC `UserPromptSubmit`: 슬롯 작업중 표시 (+ `/new`/`/clear` 후 session-id 드리프트 자가치유 → 답장/첨부 라우팅 유지) |

## 설치

**Python ≥ 3.9**, **Node.js**(pm2용), 그리고 [@BotFather](https://t.me/BotFather)의 Telegram 봇 토큰이 필요합니다.

### 원라인 설치(권장)

양쪽 플랫폼 모두 전부 설치합니다 — pm2 데몬 + 재부팅 생존, Telegram 명령 메뉴, Claude Code 훅, 초기 고정 상태 보드. 멱등이며 재실행해도 안전합니다.

**Windows**(PowerShell):
```powershell
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
pip install -e .
python -m imadhd install
# 또는 비대화형:
python -m imadhd install --token 123:ABC --chat <YOUR_CHAT_ID>
```

**Linux**(bash):
```bash
git clone https://github.com/chan12392/ImADHD.git
cd ImADHD
pip install -e .
python -m imadhd install
# 비대화형:
python -m imadhd install --token 123:ABC --chat <YOUR_CHAT_ID>
```

설치는 4단계를 수행합니다:
1. **pm2** 설치 + 재부팅 생존(Windows: `pm2-windows-startup` + Node를 절대경로로 호출하는 강화된 `resurrect.cmd`, 그리고 `schtasks` ONLOGON 백업, Linux: `pm2 startup systemd`), 이후 라우터 데몬 시작.
2. **Telegram 명령 메뉴** — *병합*합니다, 덮어쓰지 않음: 기존 봇 명령은 보존하고 충돌 이름만 교체.
3. **Claude Code 훅** — `SessionStart` / `Stop` / `PreToolUse(AskUserQuestion)` / `UserPromptSubmit`를 `~/.claude/settings.json`에 추가(멱등, 기존 훅 유지). 토큰/채팅은 `~/.imadhd/env`(0600)에 기록 — `settings.json`의 전역 `env`가 아니라 — 구 버전 설치가 거기 박아둔 토큰이 있다면 마이그레이션.
4. **Telegram pin** — 최초 실행 시 상태 보드 생성 및 고정.

플래그: `--token`, `--chat`, `--max-slots N`(기본 6), `--skip-pm2`, `--skip-pin`.

> 설치는 `TELEGRAM_ALLOWED_CHAT_ID`([@userinfobot](https://t.me/userinfobot)의 본인 사용자 id)를 요구하고 없으면 진행을 거부합니다 — 공개된 봇 토큰만으로 누구나 당신의 터미널을 구동할 수 있으므로 **fail-closed**로 강제합니다.

### 제거

한 줄이 설치가 한 모든 것을 — 역순으로, 외과적으로, 본인 커스터마이징은 보존하며 — 되돌립니다:

```bash
python -m imadhd uninstall          # 확인 프롬프트
python -m imadhd uninstall --yes    # 비대화형(자동화)
python -m imadhd uninstall --skip-pm2
```

순서대로 제거합니다:
1. **pm2** ImADHD 프로세스 + `pm2 save`(Windows: ONLOGON `schtasks` 엔트리, Linux: `sudo pm2 unstartup systemd` 직접 실행 — root 필요).
2. **Telegram 명령 메뉴** — *외과적*: ImADHD 명령 이름만 필터링(`default`와 `all_private_chats` 양쪽 scope), 본인 봇 명령은 보존. 빈 scope → `deleteMyCommands`.
3. **Claude Code 훅** — 4개 ImADHD 훅 그룹을 `~/.claude/settings.json`에서 제거, 다른 훅/설정은 미동. 먼저 **민감정보 마스킹된** 백업(`settings.json.bak-uninstall-<ts>`, 0600) 기록.
4. **Telegram pin** — `unpinChatMessage` + 삭제(best-effort).
5. **data_dir**(`~/.imadhd`, 토큰 `env` 포함) — 완전 삭제.
6. **`repo/.env`** — ImADHD 키만 제거, 남는 게 없으면 파일 삭제, 있으면 0600으로 재작성.

토큰은 어디에도 출력/로그되지 않습니다. 모든 단계는 멱등입니다 — 없는 항목은 건너뜁니다. repo 디렉토리와 pip 패키지는 직접 제거하세요(`rm -rf ImADHD && pip uninstall imadhd`).

### 수동(폴백 / 개발)

```bash
pip install -e .            # 런타임 의존성(python-dotenv)
pip install -e ".[dev]"     # + 테스트 / 린트
cp .env.example .env       # 이후 값 채우기
```

`.env.example`이 모든 변수를 문서화합니다, 수동 훅 + pm2 단계는 아래에.

## 사용법

Claude Code 창을 엽니다(Windows) 또는 `tmux` attach + Claude Code 실행(Linux). `SessionStart` 훅이 슬롯을 할당하고 상태 보드에 `⭕`이 뜹니다. 그 다음 Telegram에서 구동:

### 터미널에 메시지 보내기
슬롯 번호 뒤에 메시지. 둘 다 동작:
```
3️⃣ 로그 확인하고 요약해
3 로그 확인하고 요약해
```
3번 터미널에 주입됩니다. 주입 시 해당 세션에 **pending 플래그** 설정, Claude Code가 끝나면 `Stop` 훅이 플래그를 보고 답장을 캡처해 `3️⃣` 접두와 함께 폰으로 보냅니다. 길이 제한을 넘는 답장은 "짧게 줘" 넛지와 함께 한 번 튕겨집니다. 터미널에 **직접** 타이핑한 작업은 pending 플래그가 없어 로컬에만 — Telegram으로 새지 않습니다.

### 명령
| 명령 | 하는 일 |
|---|---|
| `3️⃣ <text>` / `3 <text>` | `<text>`를 3번 터미널에 전송(pending target으로 설정) |
| `/list` | 활성 터미널 + 슬롯 상태 표시 |
| `/new <N>` | N번 터미널을 `/clear`로 리셋하여 새 대화 — 예: `/new 1` |
| `/open` | 홈 디렉토리에 새 터미널 열기(Windows: 새 WT 창, Linux: 새 tmux 세션). 홈 기반이라 CC가 기존 프로젝트 & resume 세션을 인식. |
| `/close <N>` | 터미널 종료 — `/close 1`, 다중 `/close 1 2 3` 또는 `/close 1,2,3`, 전체 `/close all` (Windows: WT 탭 트리 전체 종료) |
| `/stop <N>` | N번 터미널에 ESC 전송, 현재 작업 중단 |
| `/use <N>` | N번 터미널을 **sticky 기본**으로 — 번호 없는 메시지가 변경 전까지 그곳으로 라우팅. `/use off`로 해제 |
| `/pin` | 고정 상태 보드 새로고침 |
| `/help` | 명령 도움말 |
| `/doctor` | 자가 진단 — 라우터 heartbeat, 슬롯, pin, 훅, pm2 상태 |
| `/update-adhd` | 자가 업데이트 — 현재/최신 버전 + 최신 CHANGELOG 표시 후 **예/아니오** 인라인 확인, 그 다음 `git pull` → `pytest` → `pm2 restart`(테스트 실패 시 재시작 거부) |

> **팁:** 사실 이 명령들을 타이핑할 일이 거의 없습니다. 상태 보드의 `ReplyKeyboard`가 **기능버튼 우선** — `📋 /list`, `📂 /open`, `✖️ /close`, `🎯 /use`, `🔄 /update-adhd`, … 를 직접 탭. `/close /stop /use /new`는 버튼 탭 시 활성 터미널만 보여주는 **인라인 slot picker** 팝업(번호 탭하면 실행), 활성 터미널이 하나면 picker 없이 즉시 실행.

### 상태 보드(고정)
고정 메시지가 모든 슬롯을 표시: ⭕ 대기 / 📝 작업중 / ⏳ 대기중 / ❌ 죽음. `ReplyKeyboard`는 **기능버튼 우선** — 명령 버튼 4행(`📋 /list`, `📌 /pin`, `🆕 /new`, `📂 /open`, `✖️ /close`, `⏹ /stop`, `🎯 /use`, `❓ /help`, `🩺 /doctor`, `🔄 /update-adhd`) 위에 메시지 주입용 간결한 1️⃣–6️⃣ 번호 키패드. 슬롯 상태가 바뀌면 자동 새로고침.

> **단일 터미널 단축:** 활성 슬롯이 하나뿐이면 번호를 생략해도 — bare 메시지가 자동으로 그 터미널에 주입됩니다. **2개 이상**이고 번호/sticky/pending도 없으면, bare 메시지 대신 인라인 **"↘️ 어느 터미널로 보낼까?"** 버튼이 팝업 → 슬롯 탭하면 그곳으로 주입(10분간 대기).

### 이미지(양방향)
- **CC → Telegram**: Claude Code 답장에 이미지가 실려 오면(생성한 PNG, 본인이 찍은 스크린샷), 텍스트 답장과 함께 `sendPhoto`로 폰에 전송 — hand-rolled `multipart/form-data`(`requests` 무의존). 한 답장에 여러 이미지면 각각 별도 메시지로.
- **Telegram → CC**: 봇에게 사진을 보내면 가장 큰 사이즈를 `~/.imadhd/inbox/tg_<file_id>.jpg`로 다운로드(원자적 쓰기), 활성 CC 슬롯은 `이미지 수신: <path>`를 받고 그 경로의 파일을 `Read`로 분석 가능.

## 설정

`.env` 편집:

| 변수 | 필수 | 내용 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **예** | @BotFather 토큰 |
| `TELEGRAM_ALLOWED_CHAT_ID` | **예** | 본인 Telegram 사용자 id — [@userinfobot](https://t.me/userinfobot)에서 확인 |
| `IMADHD_MAX_SLOTS` | 아니오 | 최대 번호 터미널 수(기본 `6`) |
| `IMADHD_DATA_DIR` | 아니오 | 런타임 데이터 디렉토리(기본 `~/.imadhd`) |
| `IMADHD_TRANSPORT` | 아니오 | 입력 전송 — `pipe_win`(Windows, 포커스 无, **권장**), `sendkeys_win`(Windows, 포커스 강탈 폴백), `tmux_linux`(Linux). `.env` 값이 최우선이며 ambient env var를 덮어씁니다. |
| `IMADHD_REPLY_MARKER` | 아니오 | 레거시 보조 신호(기본 `[A.D.H.D]`). 답장 라우팅은 프롬프트의 마커가 아닌 주입 시점의 **pending 플래그**로 구동 — 구 주입 경로용 폴백일 뿐. |
| `IMADHD_INJECT_METHOD` | 아니오 | Windows 전용: `paste`(clipboard+Ctrl+V, 빠름, 기본) 또는 `type`(문자별 SendInput, 레거시) |
| `IMADHD_SKIP_PERMS` | **아니오 — 위험** | Linux 전용: `1`이면 Claude Code를 `--dangerously-skip-permissions`로 실행. 기본 off — Telegram 토큰 탈취 시 호스트에서 임의 명령이 가능함을 감수할 때만. |
| `IMADHD_ALLOW_ANY_CHAT` | **아니오 — 개발 전용** | `1`이면 allow-list 없이 모든 채팅 허용. **공개 봇에서는 절대 금지.** |

> **🔒 `TELEGRAM_ALLOWED_CHAT_ID`는 fail-closed로 강제.** 봇 토큰을 가진 누구나 당신의 터미널을 구동할 수 있으므로, 설정되지 않으면 라우터는 **시작을 거부**합니다. `IMADHD_ALLOW_ANY_CHAT=1` 탈출구는 로컬 테스트 전용.

> **🔐 비밀 저장소.** 설치가 봇 토큰을 두 파일에 기록, 둘 다 Linux/macOS에서 `0600`: `repo/.env`(라우터)와 `~/.imadhd/env`(Claude Code 훅). 훅은 거기서 `config.Settings.load()`로 불러옵니다 — `~/.claude/settings.json`의 전역 `env`가 아니라 — 토큰이 모든 Claude Code 세션과 서브프로세스에 새어나가지 않습니다.

## Claude Code 훱 설정

> **원라인 설치가 이미 처리합니다.** 이 섹션은 수동 설정 / 참고용.

`~/.claude/settings.json`에 추가:

```jsonc
{
  "hooks": {
    "SessionStart":      [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.register_hook" }] }],
    "Stop":              [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.reply_hook"    }] }],
    "UserPromptSubmit":  [{ "hooks": [{ "type": "command", "command": "python -m imadhd.hooks.busy_hook"     }] }],
    "PreToolUse":        [{ "matcher": "AskUserQuestion|Bash|Write|Edit",
                            "hooks":  [{ "type": "command", "command": "python -m imadhd.hooks.dispatch_hook", "timeout": 300000 }] }]
  }
}
```

> **`PreToolUse` 1개 엔트리, 2가지 동작.** `dispatch_hook`이 stdin을 1회 파싱 후 `tool_name`으로 분기 — `AskUserQuestion` → 명확화 질문 인라인 버튼, `Bash`/`Write`/`Edit` → 위험 도구 예/아니오 게이트. (이전 릴리스는 `ask_hook`·`perm_hook`을 별도 엔트리 2개로 등록했으나, 재설치 시 단일 `dispatch_hook` 엔트리로 자동 마이그레이션됩니다.)

**`AskUserQuestion`** 경로는 Claude Code의 명확화 질문을 터미널에서 멈추는 대신 **Telegram 인라인 버튼**으로 보냅니다. 옵션 탭 → 답이 Claude Code로 되먹여지고 작업 계속 — 폰→터미널 왕복 없음. 타임아웃 내 답이 없으면 질문이 거부됩니다(Claude Code가 다시 물어볼 수 있음). `TELEGRAM_ALLOWED_CHAT_ID`가 설정되지 않았을 때는 no-op 폴백(네이티브 프롬프트 표시).

**`Bash|Write|Edit`** 경로(`perm_hook`)는 **위험 도구 호출** — `rm`, `git push`, `kill`, `sudo`, `drop`, 보호 디렉토리 쓰기 등 — 을 Claude Code가 실행하기 전 Telegram **예/아니오**로 라우팅. 안전한 도구(`ls`, `cat`, 보호 경로 외 편집)는 지연 0으로 자동 허용. 훅의 `permissionDecision: deny`는 **`bypassPermissions` 모드에서도** 존중 — 훅이 permission-mode 체크 전에 발동하므로 폰에서의 최후 관문. 타임아웃 → 거부(fail-closed). Telegram 마커 없는 터미널 직접 턴은 건너뛰어 로컬 작업이 결차단되지 않습니다.

> **`CLAUDE.md` 룰 불필요.** 답장은 Claude Code가 찍어야 할 후행 마커가 아닌, 주입 시점에 설정된 **pending 플래그**로 라우팅. Claude Code는 턴이 Telegram에서 왔는지 전혀 모릅니다 — 프롬프트 접미사도, 마커 에코도, 잊을 수 있는 행동 룰도 없습니다.

## 라우터 실행

> **원라인 설치가 이미 처리**(pm2 데몬 + 재부팅 생존). 수동 제어 / 참고용.

```bash
pm2 start "python -m imadhd.cli router" --name imadhd --cwd "$PWD"
pm2 logs imadhd      # 예상: "router start: slots=6 ..."
```

## 플랫폼 메모

- **Windows** — `pipe_win`(기본)이 Telegram 입력을 named pipe로 보내 `host.py` PTY-bridge에 넣어, 입력이 **포커스를 뺏지 않고** 터미널에 도착. 봇의 `/open` 명령으로 터미널을 열면 자동으로 `host.py` 아래 시작됩니다. `sendkeys_win`은 레거시 폴백: 대상을 먼저 전경으로 강제하는 ctypes 네이티브 `send_keys` — `IMADHD_TRANSPORT=sendkeys_win`으로 선택. `sendkeys_win`의 경우 `IMADHD_INJECT_METHOD=paste`(clipboard+Ctrl+V, 기본)가 문자별 `type`보다 훨씬 빠름.
- **Linux** — 입력은 `SessionStart`에 캡처한 pane으로 `tmux send-keys`. 각 Claude Code 세션은 자기만의 tmux session/pane에서 실행, 레지스트리가 올바른 대상을 가리키기 위해 `tmux_pane`을 추적. `IMADHD_TRANSPORT` 미설정 시 자동 감지.

## 확장
- **새 입력 방식**(ssh / pty): `Transport.inject()`를 구현하는 `imadhd/transports/yourmethod.py` 추가. 코어 미수정.
- **새 명령**(`/status`): `Command`를 구현하는 `imadhd/commands/status.py` 추가 후 `setup_commands.build_commands`에 등록. 코어 미수정.
- **다른 답장 채널**(Discord): `boards/` + `telegram_api/`를 미러링.

## 라이선스
MIT — [LICENSE](LICENSE) 참조.
