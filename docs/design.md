# ImADHD — 다중터미널 텔레그램 라우터 설계 spec

- 작성: 2026-07-02
- 작성자: ImADHD
- 상태: 승인됨 (구현계획 대기)

---

## 1. 목표

사용자가 **외부에서 텔레그램 DM 하나**로, 데스크톱에 띄워둔 **여러 Claude Code 세션 중 하나를 골라 작업 지시**하고 답변을 받는다.

- 기본은 터미널 직접 소통. 텔레그램은 "외출 시 이어가기"용.
- 하나의 텔레그램 봇 = 여러 CC 세션(최대 6) 라우팅.
- 각 세션은 번호(1~6)로 구분. **가장 먼저 띄운 CC = 1번**, 다음 = 2번 …
- DM 앞에 숫자 이모지(`1️⃣`~`6️⃣`)가 없으면 아무 세션도 반응 안 함.

## 2. 핵심 원칙

**CC는 텔레그램을 직접 모른다.** pm2 폴링 데몬(btg-router)이 유일하게 텔레그램과 통신하고, CC에게는 `send_keys` 키 주입으로 요청을 전달한다. CC의 답변은 Stop 훅이 transcript에서 캡처해 텔레그램으로 회신한다.

→ CC 본체 변경 최소화. 텔레그램 봇 토큰, pm2, python 인프라 재사용.

## 3. 아키텍처

```
                 ┌───────────────────────────┐
   사용자  ──DM──▶│  Telegram Bot              │
   (외부)         └─────────────┬─────────────┘
                               │ getUpdates (롱폴)
                 ┌─────────────▼─────────────┐
                 │  pm2: btg-router (라우터)  │
                 │  - 숫자이모지 파싱          │
                 │  - registry 조회           │
                 │  - 사전체크(IsWindow/pid)  │
                 │  - ack 텔레그램 전송        │
                 └─────┬───────────────┬──────┘
        주입(send_keys)│               │ 회신(Bot API)
                       │               │
        ┌──────────────▼──┐    ┌───────▼──────────────┐
        │ send_keys       │    │ Stop 훅              │
        │ (포커스→타이핑) │    │ btg-reply            │
        └──────────────┬──┘    │ - transcript 읽기    │
                       │       │ - 마커 감지          │
            ┌──────────▼────┐  │ - session_id→번호   │
            │  CC-N 세션    │──┘ - 답변 텔레그램 전송 │
            │ (CC-N)        │
            └───────────────┘

   registry.json ◀── 등록: SessionStart 훅 btg-register
     {번호: {session_id, hwnd, pid, cwd, started_at}}
```

## 4. 컴포넌트

### 4.1 registry.json (런타임 상태)
- 경로: `~/.imadhd/registry.json`
- 구조:
```json
{
  "1": {"session_id":"...", "hwnd":12345678, "pid":999, "cwd":"...", "started_at":"..."},
  "2": {...},
  "3": null,
  ...
  "6": null
}
```
- 번호 = **가장 낮은 빈 슬롯** 자동 할당. 종료/죽으면 `null` 로 반납.
- 동시쓰기 방지: 파일 록(단순 atomic write — 임시파일 쓰기 후 rename).

### 4.2 SessionStart 훅 — `btg-register`
- 위치: `imadhd/hooks/register_hook.py` (entry: `btg-register`)
- 역할: CC 세션 시작 감지 → 빈 번호 클레임 → registry 등록.
- 절차:
  1. stdin payload에서 `session_id`, `cwd` 확보.
  2. registry 잠금 → 가장 낮은 빈 번호(1~6) 선택. 6개 꽉 차면 `7` 이상 거부 + 텔레그램 경고.
  3. **HWND 캡처 (pid 기반 결정론적, 2026-07-03 수정)** — `console_hwnd(cc_pid)` 우선: CC pid(claude.exe)에서 `AttachConsole→GetConsoleWindow→PseudoConsole owner` 로 창 역추적. 포그라운드 레이스 무관, 세션마다 고유 hwnd. 1 WT 창 다중CC(탭)에선 ConPTY owner 가 공유/비top-level 이라 주입 SetForegroundWindow 가 안 통하므로 **운용상 CC 1세션 = WT 창 1개(창 분리)** 권장. `console_hwnd` 실패 시 폴백 `GetForegroundWindow()` → 자기 콘솔.
  4. pid(현재 프로세스 또는 부모) 기록.
  5. registry 갱신 해제.
  6. 텔레그램 알림: `✅ N번 터미널 연결됨 (PID xxxx, cwd)`.
- 동일 session_id(또는 동일 pid) 재시작 시 기존 슬롯 재사용(덮어쓰기).

### 4.3 pm2 폴링 데몬 — `btg-router`
> ⚠ **14절에서 개정**: 주입 프롬프트에 `[A.D.H.D]` 마커를 부착하던 동작(아래 6.)은 **제거** — 이제 마커 없이 본문만 주입. Windows 기본 transport 도 `sendkeys_win` → `pipe_win`(14.1)으로 전환.

- 위치: `imadhd/cli.py` (entry: `btg-router`)
- pm2 이름: `imadhd`
- 역할: 텔레그램 롱폴 → 라우팅 → 주입.
- 절차:
  1. `getUpdates(offset)` 롱폴. offset 은 `~/.imadhd/offset.txt` 에 영구 저장(pm2 재시작 시 중복 처리 방지).
  2. 메시지 본문 선두의 **숫자이모지(`1️⃣`~`6️⃣`) 또는 슬래시(`/1`~`/6`)** 파싱.
     - **둘 다 아니면 무시** (아무 반응 안 함).
     - `/N` 단독 = 버튼 클릭과 동일(선택모드 pending). `/N <본문>` = 즉시 주입. `/10` 등 두자리는 무시.
     - 단 예외 명령(번호 없이): `/list`(=`/터미널`) → 현재 registry 활성 목록 전체 전송.
  3. 번호 → registry 조회.
  4. **사전체크** (리스크2 완화):
     - `IsWindow(hwnd)` + pid 프로세스 생존 확인.
     - 죽었으면 → registry 해당 슬롯 `null` 처리 → 텔레그램 `❌ N번 터미널 꺼져있음` → 입력 중단.
  5. 살았으면 ack 전송: `📩 N번 ← <본문 요약>`.
  6. `imadhd/transports/sendkeys_win.py` 로 `--hwnd <hwnd> --text "<본문>\n\n[A.D.H.D]"` 주입.
     - 입력: 기본 **포커스 강제** (v1). `--bg` 옵션 시 베타 백그라운드 시도 (리스크3).
  7. 다음 offset 으로 갱신.

### 4.4 Stop 훅 — `btg-reply`
> ⚠ **14.2에서 개정**: 마커 echo 감지 기반 회신(아래 3.)은 **폐지** — 이제 회신 여부는 주입 시 세팅되는 **pending 플래그** + 길이 게이트로 결정. 마커는 더 이상 회신 조건이 아님.

- 위치: `imadhd/hooks/reply_hook.py` (entry: `btg-reply`)
- 역할: CC 응답 종료 시 답변 캡처 → 텔레그램 회신.
- 기존 `channel-reply-guard.py`(Stop 훅)과 **별도 추가**, 공존.
- 절차:
  1. stdin payload에서 `session_id`, `transcript_path` 확보.
  2. transcript JSONL 의 마지막 assistant 메시지 본문 읽기.
  3. 본문 말단에 `[A.D.H.D]` 마커 있는지 확인.
     - 없으면 종료 (일반 터미널 응답 → 회신 안 함).
  4. 있으면 → 마커 **제거한 본문** 추출.
  5. registry 역조회: `session_id → 번호`.
  6. 해당 번호 숫자이모지를 본문 앞에 붙여 텔레그램 전송. (번호 못 찾으면 그냥 전송.)
  7. `stop_hook_active=True` 면 통과(무한루프 방지).

### 4.5 PreToolUse 훅 — `btg-ask` (AskUserQuestion → 인라인 버튼)
- 위치: `imadhd/hooks/ask_hook.py` (entry: `btg-ask`), 저장소 `imadhd/core/ask_manager.py`.
- 역할: CC 가 `AskUserQuestion`(사용자에게 묻는 선택 질문) 호출 시 **네이티브 터미널 UI 대신 텔레그램 인라인 버튼**으로 질문 송신. 버튼 탭 → 답이 CC 에 `updatedInput.answers` 로 주입 → 작업 계속. (Notification 훅은 AskUserQuestion 에 안 붙으므로 PreToolUse 필수.)
- 흐름:
  1. PreToolUse payload `{tool_name:"AskUserQuestion", tool_input:{questions:[...]}}` 파싱.
  2. 질문마다 1개 메시지(옵션=인라인키보드 행) 송신. `callback_data="a:<ask_id>:<item>:<opt>"`.
  3. ask 기록 `data_dir/asks/<ask_id>.json` 작성(원자적 쓰기).
  4. **폴링 대기**(1s 간격, 최대 `IMADHD_ASK_TIMEOUT`=280s 기본).
     - router 가 callback_query 받아 `items[i].answer` 기록 → 전원 답 시 `status=answered`.
  5. 답 도착 → `hookSpecificOutput.permissionDecision:"allow"` + `updatedInput={...tool_input, answers:{<질문>:<라벨>}}`. (CC 가 이 answers 를 받아 질문 해소.)
  6. 시간초과 → `permissionDecision:"deny"` + 사유("텔레그램 응답 시간초과"). 모델이 사유 보고 다시 질문 유도.
- 폴백: `TELEGRAM_ALLOWED_CHAT_ID` 미설정/송신 실패 → 빈 출력 → CC 네이티브 UI(사용자 차단 안 함).
- 보안: callback 도 allowed chat 만(fail-closed). ask_id 미존재/만료/중복클릭 → 토스트만 안내, 무시.
- 라이브 검증 필요(2026-07-03): CC 가 `updatedInput.answers` 를 실제로 AskUserQuestion 답으로 소비하는지 최초 트리거 시 확인.

### 4.6 send_keys transport — `imadhd/transports/sendkeys_win.py`
- 위치: `imadhd/transports/sendkeys_win.py`
- 기능:
  - HWND 직접 지정 주입: 번호로 창 찾는 대신 registry 의 HWND 로 직접.
  - `background=True` 옵션(**베타, 기본 off**): 백그라운드 입력(PostMessage WM_CHAR/WM_KEYDOWN) 시도.
    - **도달 보장 없음**: PostMessage는 입력이 실제로 도달했는지 반환하지 않음. Windows Terminal 자식창 겹겹 구조라 일부 창에만 닿음.
    - 실패 감지 불가 → 폴백 트리거 애매 → v1은 **기본 포커스 강제**로 확실 입력 보장.
    - 추후 conpty 기반 안정 메커니즘 확보 시 백그라운드 기본 전환 검토.
- 기본 동작 = HWND 찾아 포커스 강제 후 타이핑 (v1 기준).

### 4.6b 터미널 라이프사이클 명령 — `/open` `/close N` `/stop N` (2026-07-04)
- `imadhd/commands/open_command.py`: `/open` — `wt -w new new-tab --title Claude cmd.exe /c claude` 를
  detached spawn. SessionStart 훅이 새 세션을 자동 번호 할당(연결 알림은 아래 참고). 토큰 분리
  배열 형태(`[WT,"-w","new","new-tab",...]`)로 spawn — 문자열 결합 시 wt 인자 파싱 실패(실측, 따옴표
  중첩 문제) 확인됨.
- `imadhd/commands/close_command.py`: `/close N` — ①`WM_CLOSE` PostMessage(graceful) ②
  `taskkill /F /PID <cc_pid> /T`(보측, claude 강제종료→cmd→WT 탭 closeOnExit 연쇄) ③registry.release.
- `imadhd/commands/stop_command.py`: `/stop N` — 진행 중 작업 중단. `transport.send_key(target, VK_ESCAPE)`
  로 ESC 1개 전송(CC TUI 관례: ESC=현재 generation/tool 중단).
- `Transport.send_key()`: base.py 에 추가된 신규 추상 메서드(기본 NotImplementedError). Windows
  구현(`sendkeys_win.py`)은 `_acquire_focus()`(구 `_focus_type` 리팩터, 텍스트주입과 공유) 후
  `keybd_event` keydown/keyup.
- 봇 메뉴(setMyCommands) 및 `/help` 텍스트에 반영 완료.

### 4.6c 연결/종료 알림 제거 + `/list` 창 제목 표시 (2026-07-04, 대표님 피드백)
- **배경**: "N번 터미널 연결됨/종료" 자동 알림이 채팅을 지저분하게 만든다는 대표님 지적(처음엔
  무음 전송으로 완화 시도 → 재지적 받고 아예 제거로 정정).
- `register_hook.py`: 연결 성공 알림 완전 제거. 슬롯 만실(등록 실패, 실제 조치 필요) 알림만 유지.
- `router.py`: sweep 루프의 "❌ N번 종료" 알림 제거. 상태는 상태보드(pin)와 `/list` 로 확인.
- `list_command.py`: 표시 항목을 `PID + cwd` → **창 제목**(`proc_win.window_title(hwnd)`)으로 교체.
  hwnd 무효/제목 빈 문자열이면 `cwd` 로 폴백(정보 손실 방지).
- `proc_win.py`: `window_title(hwnd)` 추가 — `GetWindowTextW` 래핑, 실패 시 `""`.

### 4.7 Claude Code 규칙 추가 (CLAUDE.md)
> ⚠ **14.2에서 폐지**: CLAUDE.md 의 마커 echo 규칙은 **삭제됨**(2026-07-06). 회신 라우팅이 pending 플래그 기반으로 전환되어 CC 가 텔레그램 인입 사실을 모르게 됨. 아래 규칙 텍스트는 역사 기록.
`~/.claude/CLAUDE.md` 의 절대규칙 블록에 추가:
> **텔레그램 요청 응답 규칙**: 프롬프트에 `[A.D.H.D]` 표시가 있으면, 표는 쓰지 말고(모바일 미렌더)
> 핵심만 짧게(의미 단위 줄바꿈) 답한 뒤, 최종 답변의 **마지막 줄에 반드시 `[A.D.H.D]` 문구 출력**.
> (Stop 훅 회신 트리거.)

추가로 `reply/markup.py` 에 `flatten_tables()` 도입 — CC 가 규칙을 어기고 표를 출력해도
`md_to_tg_html()` 이 표를 자동으로 `가운뎃점 구분 평문 줄`로 평탄화(2차 방어). 구분선(`|---|---|`)
행은 통째로 제거, 코드펜스 내부 표는 보존(건드리지 않음).

### 4.8 봇 명령 메뉴 자동 등록 (setup)
`python -m imadhd adhd [bot_token]` → setMyCommands 로 봇 `/` 자동완성 메뉴 등록 (OSS 사용자 설치 후 1회).
- `/1`~`/N`: "N번 터미널로 메시지 전송" (InjectCommand — `/N 본문`=즉시주입, `/N` 단독=pending)
- `/list`: "활성 터미널 목록 보기" (ListCommand TRIGGERS `/list`·`/터미널` 지원)
- 토큰: 인자 OR `.env` `TELEGRAM_BOT_TOKEN`. 인자 평문 = shell history 노출 → **.env 권장**.
- 모듈: `imadhd/setup_commands.py`(`build_commands` + `register`), `telegram_api/client.set_my_commands`.

## 5. 데이터 흐름 (정상 케이스)

```
[사용자 텔레그램] "3️⃣ 빌드 로그 확인해줘"
  → getUpdates
  → 번호=3, 본문="빌드 로그 확인해줘"
  → registry: 3 → {hwnd_3, pid_3}
  → 사전체크: IsWindow(hwnd_3)=true, pid_3 살음
  → ack 텔레그램: "📩 3번 ← 빌드 로그 확인해줘"
  → send_keys --hwnd hwnd_3 (포커스 강제) → 타이핑:
      "빌드 로그 확인해줘
       [A.D.H.D]"
      ENTER
  → CC-3 정상 처리
  → CC-3 답변: "...로그 분석 결과...\n\n[A.D.H.D]"
  → Stop 훅: transcript 마지막 assistant 읽기 → 마커 감지
  → 본문 추출(마커 제거) → session_id → 3
  → 텔레그램: "3️⃣ ...로그 분석 결과..."
```

## 6. 번호 매핑 라이프사이클

| 이벤트 | 동작 |
|---|---|
| CC 시작 | SessionStart 훅 → 가장 낮은 빈 번호 할당 + HWND/pid 등록 |
| CC 정상 사용 중 | registry 유지, send_keys/Stop 훅이 참조 |
| CC 종료(정상) | (감지 어려움) → 다음 사전체크 시 슬롯 회수 |
| CC 비정상 종료 | send_keys 사전체크(IsWindow=false) 시 슬롯 `null` + 텔레그램 에러 |
| 동일 session_id(또는 pid) 재시작 | 기존 번호 슬롯 덮어쓰기 |
| 6개 꽉 찬 상태서 시작 | 거부 + 텔레그램 경고("모든 슬롯 사용 중") |
| 사용자 `/list` | 현재 활성 registry 목록 텔레그램 전송 |

## 7. 리스크 & 완화

1. **포커스 강제 전환** — N번 주입 시 N번 창이 화면에 튀어나옴.
   - 사용자 수용 (외출 시나리오에서는 무방).
   - 완화: 백그라운드 입력 우선 시도(리스크3)로 가능한 한 포커스 안 빼앗음.
2. **registry 스테일 슬롯** — send_keys **직전 사전체크**(IsWindow + pid)로 회수. (사용자 제안 채택)
3. **HWND 백그라운드 입력 불안정** — Windows Terminal 자식창 겹겹 구조. PostMessage 는 도달 여부 미반환 → **실패 감지 불가**.
   - 정직성 정정: **v1 기본 = 포커스 강제**(확실). `--bg` 는 베타 옵션(시도만, 도달 보장 X). "백그라운드 된다" 과장 안 함.
   - 추후 conpty/pty 기반 안정 메커니즘 확보 시 기본 전환 검토.
4. **포커스 경합** — 동시 다번호 주입 시 포커스 튕김.
   - 완화: btg-router 내부 큐 직렬 처리.
5. **pm2 orphan / offset 중복** (mem0 교훈) — offset.txt 영구 저장 + pm2 재시작 전 pid/포트/코드경로 함께 확인.

## 8. 파일 레이아웃 (모듈 패키지)

**독립 레포 + pip 패키지 구조.** 기능 추가 시 해당 모듈만 추가/변경, core 안 건드림.

```
ImADHD/                             # 레포 루트
├── pyproject.toml                  # 패키지 정의 + entry_points
├── README.md                       # 퍼블릭용: 설치/설정/사용법
├── LICENSE                         # MIT
├── .gitignore                      # .env, __pycache__, *.json(런타임), offset
├── .env.example                    # TELEGRAM_BOT_TOKEN= (예시만, 실값 X)
├── CHANGELOG.md
├── docs/
│   └── design.md                   # 본 spec
└── imadhd/                         # 패키지
    ├── __init__.py
    ├── config.py                   # 설정 로드: env/.env → 데이터객체 (시크릿 여기서만)
    ├── core/
    │   ├── registry.py             # 번호↔세션 매핑 (Registry 인터페이스 + JSONFile impl)
    │   ├── numberalloc.py          # 빈 슬롯 할당 정책
    │   ├── proc_win.py             # Windows 프로세스/창 도구 (stale HWND 복구 포함)
    │   └── router.py               # 텔레그램 폴링 + 라우팅 메인루프
    ├── transports/                 # ★확장포인트1: 터미널 입력 방식
    │   ├── base.py                 # Transport ABC: inject(target, text) -> InjectResult
    │   ├── sendkeys_win.py         # Windows ctypes send_keys (기본)
    │   └── (future: tmux.py / pty.py)
    ├── commands/                   # ★확장포인트2: 텔레그램 명령
    │   ├── base.py                 # Command ABC: match(msg)->bool, handle(...)
    │   ├── inject_command.py       # N️⃣<본문> → 사전체크 → 주입 → ack
    │   └── list_command.py         # /list → 활성 목록
    ├── boards/                     # 상태 보드 (핀 본문 + ReplyKeyboard)
    │   └── pin_board.py
    ├── reply/                      # ★확장포인트3: 답변 회신
    │   ├── base.py                 # ReplyStrategy ABC
    │   ├── marker_capture.py       # Stop 훅 마커 감지/추출
    │   └── markup.py               # markdown → Telegram HTML 변환
    ├── hooks/                      # CC 훅 (settings.json 에서 호출)
    │   ├── register_hook.py        # SessionStart: 번호할당/HWND캡처/등록
    │   ├── reply_hook.py           # Stop: 답변 캡처/회신
    │   └── ask_hook.py             # PreToolUse: AskUserQuestion → 인라인 버튼 회신
    ├── telegram_api/
    │   └── client.py               # Bot API 래퍼 (getUpdates/sendMessage, offset 영구)
    └── cli.py                      # entry_points: btg-router / btg-register / btg-reply / btg-ask
```

**확장 시나리오 (기능 추가 빠르게):**
| 추가 기능 | 작업 | core 변경 |
|---|---|---|
| 새 입력방식(tmux) | `transports/tmux.py` + config 등록 | 없음 |
| 새 명령(/상태) | `commands/status.py` + 등록 | 없음 |
| discord 회신 | `reply/discord.py` + `telegram_api/` 형태 추가 | 없음 |
| 번호할당정책 변경 | `numberalloc.py` 교체 | 없음 |

## 8b. 시크릿 분리 & 보안 (fail-closed)

- **모든 시크릿 = 환경변수 또는 `.env`** (gitignore). `config.py` 에서만 로드. 코드/커밋에 토큰 절대 금지.
- `.env.example` = 키 이름만(값 비움).
- registry.json / offset.txt = 런타임 상태 → gitignore. 예시는 `examples/`.
- 봇 토큰은 로컬 `.env`에만. 레포엔 없음.
- **`TELEGRAM_ALLOWED_CHAT_ID` 필수 (fail-closed)**: 봇 토큰만 있으면 누구나 터미널을 제어할 수 있으므로, `config.py` 는 이 값(또는 dev 전용 `IMADHD_ALLOW_ANY_CHAT=1`) 없이 기동을 거부(RuntimeError). 공개/배포 봇에서는 절대 ALLOW_ANY 를 켜지 않는다.
- git history clean 유지: 초기 커밋부터 시크릿 없음 (공개 전 `git log -p | grep 토큰` 점검).
- Windows 전용 기능(sendkeys) → README에 플랫폼 명시, transports 인터페이스로 타OS 확장 열어둠.

## 9. settings.json 훅 등록

- `SessionStart`: `btg-register` 추가 (matcher: startup).
- `Stop`: `btg-reply` 추가 (기존 `channel-reply-guard.py` 유지, 별도 엔트리).
- `PreToolUse`: `btg-ask` 추가 (matcher: `AskUserQuestion`, timeout 300000ms). 기존 `recall_hook.py`(matcher `Bash|Write|Edit`)과 **별개 엔트리** → 충돌 없음.
- 기존 `telegram-new-command.py`(UserPromptSubmit)는 채널 래퍼 인입만 매칭 → 우리 send_keys 타이핑은 채널 래퍼 없음 → **충돌 없음, 유지**.

## 10. 구현 순서 (요약, 상세는 writing-plans)

1. 디렉토리 + registry.json 초기화(offset 6슬롯 null).
2. `btg-register` (SessionStart) — 번호 할당/HWND 캡처/등록.
3. `sendkeys_win.py` — HWND 직접 주입, `--bg` 옵션.
4. `btg-router` (pm2) — 폴링/파싱/사전체크/주입/ack.
5. `btg-reply` (Stop) — 마커 감지/본문 추출/회신.
6. settings.json 훅 2개 등록.
7. CLAUDE.md 규칙 추가.
8. pm2 `imadhd` 시작 + 수동 E2E (사용자 텔레그램 → CC 1~2개 띄워서 번호 라우팅/회신 검증).

## 11. 미해결 / 추후

- HWND 캡처 타이밍: SessionStart 실행 시점과 실제 터미널 창 포커스 시점 차이 → prewait + 재시도 폴백. (현재는 주입 시 `console_hwnd(pid)` 로 stale HWND 자동 재탐색으로 완화.)
- 백그라운드 입력 감지 신뢰성: Windows Terminal 버전별 차이 → 실패 시 즉시 폴백 보장.
- CC 정상 종료 감지: SessionEnd 훅 부재 → 사전체크 의존. 필요시 하트비트(각 CC 주기적 ping) 추가 가능.

---

## 12. 상태 보드(ReplyKeyboard) + 선택 모드

> 추가: 2026-07-03. 사용자 UI 요구 진화에 따른 보드 형태 + 주입 흐름 개편.

### 12.1 배경 — 보드 형태 결정 과정

터미널 상태(⭕ idle / 📝 busy / ❌ dead) 시각화를 어디에 둘지 사용자 요구 진화:

1. 번호+마크 형태(`1️⃣⭕ 2️⃣❌ …`) 요청 → 인라인 키보드 핀 구현(메시지 #147).
2. "입력창 위에 영구 떠있게" → 핀(상단 고정) 배치 시도.
3. "입력창 위 말고 사진처럼 떠야 할 듯" → 사진 재해석 요청.
4. **"사진은 햄버거 메뉴가 아님, 입력창 아래에 통합된 버튼"** → 정정.
   → 실제 의도 = **ReplyKeyboardMarkup**(입력창 아래 영구 커스텀 키보드, 버튼 3열 그리드).

> 이미지 분석 도구(mcp `analyze_image`)는 사진을 "햄버거 사이드 메뉴 drawer"로 3회 오독. 사용자 정정으로 ReplyKeyboard 확정. **교훈: 해당 도구 신뢰 낮음, 로컬 재확인 또는 사용자 확인 우선.**

### 12.2 텔레그램 API 제약 (조사 결과)

사용자 후속 요구 "버튼 클릭 → 입력창에 숫자만 채우기(전송 X)":

| 시도 | 결과 |
|---|---|
| **ReplyKeyboardMarkup** | 버튼 클릭 = 무조건 **즉시 메시지 전송**. 입력창 채우기 불가. |
| **봇이 사용자 입력창 직접 조작** | 보안상 API 미지원 (Latenode/Telegram 문서 확인). |
| **switch_inline_query_current_chat** | 입력창에 `@봇유저네임 <query>` 채워지나 **inline mode 진입** → 본문 전송 흐름 깨짐(결과 패널만 표시) + 봇멘션 동반. |

→ "버튼 클릭 → 입력창만 채우기"는 **불가능** 확인.

### 12.3 채택 — 선택 모드 (ReplyKeyboard + 핀 고정 + 흔적 최소화)

사용자 결정: **ReplyKeyboard(입력창 아래) + 보드 메시지 상단 핀 고정 + 실시간 갱신 + 클릭 흔적 최소** (옵션 A).

- 보드 메시지(상태 텍스트 + ReplyKeyboard)를 **상단 핀 고정**(`pinChatMessage`). 스크롤에 안 묻힘.
- 상태 변 시 **본문 + 키보드 둘 다 실시간 갱신**(`editMessageText`에 `reply_markup` 포함). 마크(⭕📝❌) 즉시 반영.
- 버튼 텍스트/상태 텍스트 포맷: 번호이모지와 마크 사이 **점(`.`) 구분** → `1️⃣.⭕`. (숫자와 상태 시인성 분리.)
- 버튼 클릭(번호+점+상태마크) → **선택모드 대기**(pending) 등록. **안내 메시지 생략**.
- **대기 토글**: 같은 번호 재클릭 → 대기 취소. 다른 번호 클릭 → 대기 번호 교체. (사용자 요청 "한 번 더 누르면 취소, 다른 번호 누르면 변경".)
- 다음 본문 메시지(번호 없음) → 대기 번호로 주입(**600초(10분) TTL**).
- 버튼 클릭 시 어쩔 수 없이 `1️⃣.⭕` 메시지 1줄은 채팅에 남음(ReplyKeyboard 제약). 안내 회신 생략으로 부담 최소화.

### 12.4 컴포넌트 변경

**PinBoard** (`imadhd/boards/pin_board.py`):
- `status_markup()` → `{"keyboard": rows, "resize_keyboard": True}` (ReplyKeyboard). 버튼 텍스트 = `번호.상태마크`(예 `1️⃣.⭕`). `callback_data` 없음.
- `status_text()` → 동일 포맷 `번호.마크`를 공백으로 조인(본문 표시용).
- `create()` → `sendMessage`(본문+ReplyKeyboard) 후 `pinChatMessage`로 **상단 핀 고정**.
- `refresh_if_changed()` → `editMessageText`(본문 + `reply_markup` 둘 다 갱신). `(text, markup)` 키로 변경 감지, 동일 시 skip(400 "not modified" 방지).
- `repin()` → 기존 보드 메시지 delete + 재생성(포맷 교체용, `python -m scripts.repin`).
- msg_id 영구 저장: `~/.imadhd/pin_message_id.txt`.

**TelegramClient** (`imadhd/telegram_api/client.py`):
- `edit_message_reply_markup()` 추가(editMessageReplyMarkup, 400 "not modified" 무시).
- `get_updates()` → `allowed_updates=["message"]` 단순화(callback_query 미수신).

**InjectCommand** (`imadhd/commands/inject_command.py`):
- 버튼 클릭 감지: 본문에서 점(`.`) 제거 후 상태마크(`⭕❌📝`)만 또는 빈 값이면 선택모드 분기.
  - **대기 토글**: `ctx.pending[chat]` 기존 번호 == 클릭 번호 → `del`(취소). 아니면(신규/다른 번호) → `ctx.pending[chat]=(num, time.time())`(교체/등록). 주입/안내 없이 return.
- 본문 있으면 `do_inject()` 즉시 주입.
- `do_inject(ctx, num, body, chat)` 헬퍼: alive 재체크 + 본문 정규화(한 줄, `\n` 제거) + 마커 부착 + busy 설정. router pending 주입이 함께 사용.
- `PENDING_TTL = 600` 상수(10분).

**CommandContext** (`imadhd/commands/base.py`):
- `pending: dict` 필드 추가(`field(default_factory=dict)`). `chat_id → (num, timestamp)`.

**router** (`imadhd/core/router.py`):
- 메시지 루프: 번호 없는 본문 + `ctx.pending` 있으면 → TTL 내 `do_inject` 주입 + pending 소비. 만료 시 pending 삭제 후 일반 명령으로 폴백.
- callback_query 핸들러 제거(ReplyKeyboard는 callback 안 옴).

### 12.5 데이터 흐름 (선택 모드)

```
[사용자] 1️⃣.⭕ 버튼 클릭
  → ReplyKeyboard: "1️⃣.⭕" 메시지 즉시 전송 (채팅에 1줄 남음)
  → router: InjectCommand.match → handle
  → body=".⭕" → 점 제거 → "⭕"(상태마크)
  → ctx.pending 미사용 → pending["chat"]=(1, ts). 안내 생략.
[사용자] "로그 확인해줘" (번호 없음)
  → router: parse_leading_number=None + pending 있음 + TTL(600s) 내
  → do_inject(ctx, 1, "로그 확인해줘", chat)
  → CC-1 주입: "로그 확인해줘 [A.D.H.D]"
  → pending 소비. CC 답변 마커 → Stop 훅 회신.

[토글] 대기 중 같은 번호 재클릭(1️⃣.⭕) → pending 삭제(대기 취소).
[교체] 대기 중 다른 번호 클릭(2️⃣.⭕) → pending[chat]=(2, ts) 교체.
(600초(10분) 경과 본문 없음 → pending 자동 해제)
```

### 12.6 트레이드오프 결정 기록

| 옵션 | 채택 | 이유 |
|---|---|---|
| ReplyKeyboard(입력창 아래) + 선택모드 | ✅ | 사용자 "사진=입력창 아래 영구" + "흔적 작게" 동시 만족 가능선 |
| 인라인 핀 + callback(클릭 흔적 0) | ❌ | 채팅에 흔적 0이지만 버튼=상단 핀(입력창 아래 위배) |
| switch_inline_query_current_chat | ❌ | inline mode 진입, 본문 전송 흐름 깨짐 |

### 12.7 리스크 & 보완

1. **잘못된 터미널 주입**: pending 중 본문이 의도치 않은 메시지여도 주입됨.
   - 완화: TTL 600초(10분). 클릭 직후 바로 본문 치는 흐름 권장. **취소 토글**(같은 번호 재클릭)로 의도치 않은 대기 해제 가능.
2. **ReplyKeyboard 활성 갱신**: ~본문·버튼 분리(12.11) 후 버튼은 고정(번호만)이라 본문 edit와 무관. 활성 키보드 = keyboard_msg 고정.~
3. **버튼 클릭 메시지 잔류**: `1️⃣`(번호만) 1줄씩 채팅에 쌓임(ReplyKeyboard 불가피). 안내 회신 생략으로 줄 수 최소화.
4. **대기 상태 비가시성(해소 2026-07-03)**: 안내 생략 정책상 사용자가 어떤 번호 대기 중인지 채팅에 표시 안 됐음. → **⏳ 시각화** 추가(12.9).
5. **router 재시작 시 핀 메시지 옛날 고정(수정 2026-07-03)**: `PinBoard.__init__`이 저장된 핀 msg_id를 신뢰해 `_last_text`를 현재 active 상태로 세팅했음. registry active가 안정적(변화 없음)이면 refresh_if_changed가 edit 스킵 → 핀 메시지가 router 시작 전 옛날 상태(❌ 6개)로 영정 고정. "다른 CC 열었는데 이모지 안 바뀜" 증상.
   - **수정**: `__init__`에서 msg_id 있어도 `_last_text=None`. 첫 refresh_if_changed가 무조건 edit 시도 → 핀을 현재 상태로 강제 동기화.
6. **단일 메시지 edit 실패 → 본문·버튼 분리로 근본 해결(수정 2026-07-03)**: 12.3의 "본문+markup 단일 메시지를 editMessageText로 갱신" 설계는 Telegram 제약 충돌. `reply_markup`(ReplyKeyboard) 포함 메시지는 editMessageText 시 400 **"message can't be edited"** 반환(markup 없는 순수 텍스트만 edit 가능, 라이브 API 검증 확보). → 단일 메시지 edit이 계속 실패 → 자동 repin 발동 → "지웠다 다시 고정" 무한 반복(사용자 제보).
   - **근본 수정(12.11)**: 본문(상태 텍스트, markup 없음→edit 가능)과 버튼(ReplyKeyboard, 번호만→고정)을 **2개 메시지로 분리**. 상태 갱신은 본문만 editMessageText → 핀 고정 유지한 채 실시간 갱신, repin 발동 없음.
   - (참고) `client.edit_message_text`는 400 중 "not modified"(내용 동일, 정상)만 catch, 그 외는 raise → 상위에서 repin 유도(본문이 삭제/무효된 예외 상황용 자가복구 경로로 남김).
7. **같은 터미널이 중복 슬롯 점유 → "N번 2개" 표시(수정 2026-07-03)**: `claim_slot`이 `session_id`만 매칭했음. CC `/resume`(세션재개)는 같은 CC 프로세스(pid 동일)지만 session_id를 새로 발급 → 기존 슬롯 못 찾고 새 슬롯 점유 → 터미널 1개인데 #1·#2 두 개 표시.
   - **수정**: `claim_slot`이 `session_id` **OR `pid`** 매칭 → 같은 CC(pid)면 session 변경에도 같은 슬롯 재사용·갱신. `tests/test_registry_pid_reuse.py`로 검증(3 case 통과).

### 12.8 라이브 검증 체크리스트

- [x] 기존 인라인 핀(#147) → ReplyKeyboard(#154) 교체 (repin.py)
- [x] router 재시작 시 핀 옛날 고정 버그 수정(`_last_text=None` 강제 동기화, 2026-07-03)
- [x] pm2 `imadhd` 재시작 정상 기동 (에러 없음)
- [x] **사용자 폰 확인**: 입력창 아래 6개 버튼 표시 / 버튼 클릭 후 본문 시 주입 정상 (2026-07-03 라이브)
- [x] **본문·버튼 분리(12.11)**: 222(순수 텍스트 본문) editMessageText 정상 ok=True / 224(ReplyKeyboard) 고정 / 분리 후 400 에러 0 (2026-07-03 라이브 검증)
- [ ] 터미널 on-off 시 마크(⭕❌) 자동 변경 라이브 확인 (대기)
- [ ] 대기 토글 + ⏳ 이동 라이브 확인 (대기)

### 12.9 ⏳ 선택대기 시각화 (추가 2026-07-03)

사용자 요청: "번호 눌렀을 때 해당 번호 ⏳, 지시 넣으면 📝, 다른 번호 누르면 ⏳ 이동."

**마크 우선순위** (`PinBoard._mark_for`): `⏳ pending > 📝 busy > ⭕ idle > ❌ dead`.

- 버튼 클릭 → `ctx.pending[num]` 등록 → router `refresh_if_changed(pending_num=num)` → 핀 해당 슬롯 ⏳.
- 다른 번호 클릭 → pending 교체 → ⏳ 이동(이전 번호는 active idle → ⭕ 자동 복귀).
- 본문 주입(`do_inject`) → registry busy + pending 소비 → `refresh(pending_num=None)` → 📝.
- 같은 번호 재클릭 → pending 취소 → ⏳ 제거.

**변경**:
- `PinBoard.pending_num` 속성 + `_mark_for(info, num)` 헬퍼(status_text/markup 공용).
- `refresh_if_changed(pending_num=None)` — 매 호출마다 pending 반영.
- router: `_pending_num()` 헬퍼로 현재 pending 읽어 sweep/cmd 후 refresh에 전달. pending 주입 후엔 `None`.

### 12.10 마크다운 렌더 (추가 2026-07-03)

사용자 요청: "너가 보내는 DM에 마크다운 문법 적용 안 되는데 수정."

**원인**: 텔레그램 sendMessage 호출에 `parse_mode` 없음 → plain text 렌더(코드블록/굵게 미작동).

**변경** (`parse_mode="Markdown"`, V1 — GFM 호환, 이스케이프 느슨):
- ImADHD `client.send(chat, text, reply_markup, parse_mode)` — 파라미터 추가(기본 None). 핀/알림은 plain 유지(이모지+점이라 마크다운 불필요, 안전).
- ImADHD `reply_hook.py` 답장 전송: `parse_mode="Markdown"` + **실패 시 plain 폴백**(이스케이프 누락 400 방어).
- 기존 회신 훅(`~/.claude/scripts/channel-reply-guard.py` 계열)도 동일 패턴(폴백 경로). chunk 분할 시 코드블록 경계 잘림 가능(장문은 한 메시지 권장).

**리스크**: Markdown V1 미지원 문법(`# 제목`, `- 리스트` plain 처리). V2(이스케이프 엄격) 대안 있으나 400 위험 커 V1 채택.

**V1 → HTML 전환 (수정 2026-07-03)**: V1 채택 후에도 **코드펜스(```)** 미지원 확인. 답장에 코드블록/명령어 코드펜스 포함 시 V1 400 → plain 폴백 → "마크다운 안 됨" 증상 재발.
- **해결**: `parse_mode="HTML"` + `imadhd/reply/markup.py::md_to_tg_html()` 변환 도입. 마크다운(`**굵게**`, `` `inline` ``, ```펜스```) → Telegram HTML(`<b>`, `<code>`, `<pre><code>`). 코드 블록은 sentinel 치환(private use area)으로 내부 `* & < >` 보호 — 코드 안의 `**`가 굵게로 오해되지 않음.
- `reply_hook.py`: `md_to_tg_html(msg)` → `parse_mode="HTML"`. 변환/전송 실패 시 plain 폴백 유지.
- HTML 모드 이스케이프는 `& < >` 만이라 400 위험 최소, 코드펜스 지원 → V1보다 견고.

### 12.11 본문·버튼 분리 — 단일 핀 메시지 실시간 갱신 (최종 아키텍처, 추가 2026-07-03)

사용자 요청: "고정된 걸 계속 지웠다 다시 고정하지 말고, 한 번 고정한 걸 그냥 갱신."

**근본 원인(라이브 API 검증)**: 12.3의 "본문 + ReplyKeyboard 단일 메시지" 설계는 Telegram 제약과 충돌.
- `reply_markup`(ReplyKeyboard) 포함 메시지 → `editMessageText` 호출 시 400 **"message can't be edited"** (markup 없는 순수 텍스트만 edit 가능).
- 직접 검증: 동일 chat에서 markup 없는 msg(#220) edit **ok**, markup 있는 msg(#221) edit **400 can't be edited**.
- 결과: 매 상태 변화마다 edit 실패 → 자동 repin → **delete + 재생성 + re-pin 반복**(= "지웠다 다시 고정").

**해결 — 2개 메시지 분리** (`imadhd/boards/pin_board.py`):

| 메시지 | 역할 | 특성 |
|---|---|---|
| **status_msg**(상단 핀) | 본문 = 상태 마크 `1️⃣.⏳ 2️⃣.⭕ …` | markup **없음** → `editMessageText` 실시간 갱신 **가능** |
| **keyboard_msg**(입력창 아래) | 버튼 = 번호만 `1️⃣ 2️⃣ …6️⃣` (상태마크 없음) | ReplyKeyboard. **고정**(상태와 무관 → edit 불필요) |

- 버튼에서 상태마크 제거(번호만) → 상태 변해도 버튼 변화 없음 → keyboard_msg는 생성 1회만.
- 핀(pinChatMessage)은 status_msg에만 → 상단 고정 유지한 채 본문만 갱신.
- **상태 갱신 = status_msg editMessageText 1회**. repin(delete/re-create) 발동 안 함.

**PinBoard 변경**:
- 속성: `status_id`/`keyboard_id` + 영구 저장 파일 2개(`pin_message_id.txt`=본문, `keyboard_message_id.txt`).
- `create()`: status send(markup 없음→핀) + keyboard send(ReplyKeyboard).
- `refresh_if_changed(pending_num)`: 본문만 editMessageText(markup 없음). `_last_text`로 변경 감지(동일 시 skip, 400 방지). edit 예외(본문 무효) 시에만 `repin()`.
- `keyboard_markup()`: 버튼 텍스트 = 번호이모지+'.'(본문 `1️⃣.⭕` 시작과 일치, 상태마크 없음). 고정.
- `repin.py`: `msg_id` → `status_id`/`keyboard_id` 출력으로 수정.

**검증(2026-07-03 라이브)**: pm2 재시작 후 자동 repin 1회(status_id=222, keyboard_id=224 생성). 이후 error.log 400 없음. 222 직접 editMessageText → ok=True. 분리 구조 정상 작동, repin 루프 해소.

**트레이드오프**: 메시지 2건 사용(본문+버튼). 본문 edit = 무한 갱신 가능, 버튼 고정 = 상태 표시 불가(상태는 본문으로). 사용자 "갱신만, 삭제/재고정 금지" 요구 정확히 부합.

### 12.12 pm2 부팅 자동시작 + 버튼 점 (추가 2026-07-03)

사용자 요청: "pm2 컴퓨터 재부팅해도 자동으로 되게" + "인라인 버튼 이모지 뒤에 . 하나만."

**pm2 자동시작 (Windows)**:
- 도구: `pm2-windows-startup@1.0.3` (npm global).
- 등록 절차: `pm2 save`(현재 imadhd → `~/.pm2/dump.pm2`) → `pm2-startup install`.
- 결과: HKCU `Software\Microsoft\Windows\CurrentVersion\Run` `PM2` 키 = `wscript.exe invisible.vbs pm2_resurrect.cmd`. 로그온 시 자동 `pm2 resurrect` → dump에서 imadhd 부활.
- (주의) 작업스케줄러가 아니라 **레지스트리 Run 키** 방식. `schtasks`엔 안 보임(정상). dump에 imadhd 포함되어 있어야 부활 → 프로세스 목록 바뀌면 `pm2 save` 재실행.

**버튼 점 포맷** (`pin_board.keyboard_markup`):
- 버튼 텍스트 `1️⃣` → `1️⃣.`. 본문 `1️⃣.⭕` 시작 포맷과 일치(시인성/통일).
- 클릭 시 전송 `1️⃣.` → `inject_command.handle`: 이모지 제거 후 `body="."` → `clean=body.replace(".","").strip()=""` → 선택모드 pending 분기. 기존 파싱 로직 호환(코드 변경 불필요).
- 포맷 변경은 keyboard_msg 재생성 필요 → `repin.py` 1회 실행으로 적용(status_id=239, keyboard_id=241). 운영 중엔 재발 안 함(버튼 고정).

### 12.13 부팅 자동시작 함정 수정 — node 절대경로 (추가 2026-07-03)

**사고**: 12.12 세팅 후 재부팅 시 router 미부활. 증상 = pin/busy/주입 전부 안 됨, SessionStart 훅(`✅ N번 연결됨`)만 정상. router 부재가 원인.

**근본 원인**: `pm2-windows-startup/pm2_resurrect.cmd` 본체 = `pm2 resurrect` 한 줄(PATH 의존). HKCU Run 키가 로그온 시 wscript→cmd 체인으로 실행하지만, **wscript 실행 컨텍스트엔 사용자 PATH(`...\npm`, Node 디렉토리)가 없어** `pm2`(=node) 명령 인식 실패 → cmd 에러 종료 → pm2 daemon 자체 미기동. 최초 `pm2 list`가 daemon을 새로 spawn한 것으로 확인.

**수정**:
- `pm2_resurrect.cmd` → node 절대경로 직접 호출로 재작성. PATH/node 환경 완전 무관.
  ```bat
  "C:\Program Files\nodejs\node.exe" "%APPDATA%\npm\node_modules\pm2\bin\pm2" resurrect
  ```
- 이중화: `schtasks imadhd-pm2-resurrect /SC ONLOGON` 백업 등록(같은 cmd 부름). HKCU Run 키(기존) + 작업스케줄러(신규) 둘 다 → 어느 하나 살아도 부활.

**검증**: node 직접 호출 → `[PM2] Restoring processes` 정상 + imadhd pid 유지(online, restarts 0). 재부팅 후 자동 부활 확보.

**교훈**: Windows 로그온 자동시작(wscript/HKCU Run)은 사용자 셸 PATH를 상속하지 않을 수 있음 → node/python 등 인터프리터 호출은 **반드시 절대경로**. `pm2 resurrect`식 PATH 의존 명령은 로그온 컨텍스트에서 조용히 실패한다.

---

## 13. v0.3.0 기능 추가 (2026-07-06)

public 전환 후 모바일 UX + 자가진단 3종.

### 13.1 고정 타겟 — `/use <N>` / `/use off`

**배경**: 현행 선택모드는 `PENDING_TTL=600` 일회성 pending. 여러 터미널을 오래 다루면 매번 버튼/번호/reply가 필요해 피로.

**설계**:
- `CommandContext`에 `sticky: dict[chat_id -> slot_num]` 추가(영구, TTL 無). 라우터 프로세스 메모리 + `data_dir/sticky.json` 영속(재시작 시 복원).
- `/use 3` → `sticky[chat]=3`. `/use off` → `del sticky[chat]`.
- 본문(번호접두 無) 라우팅 우선순위:
  1. 명시 번호(`N️⃣`/`/N`) — 최우선.
  2. `reply_to` 매핑 — 명시 답장.
  3. **sticky** — 본문만 오면 sticky 타겟 주입(신규, pending보다 먼저).
  4. pending(TTL 600) — legacy 1회성.
  5. auto(활성 1개) — 폴백.
- sticky 타겟이 죽으면 자동 해제(release 시 sticky도 제거).
- **보드 표시**: sticky slot 상태라인 앞에 `🎯` 표시. `⭕🎯 3` 형태.

**토글 의미 정리**: sticky는 "이 채팅의 기본 타겟". 명시 번호 쓰면 그쪽이 우선(일시적). 본문만 보내면 sticky로. `/use off`로 해제 전까지 유지.

### 13.2 긴 답변 reply 라우팅 — 청크 전수 매핑

**배경**: `client.send()`는 4000자 초과 시 청크 분할하지만 마지막 `message_id`만 반환. `reply_hook`도 마지막 청크만 reply_map 저장. 사용자가 첫 청크에 답장하면 라우팅 미스.

**설계**:
- `send()` 반환형 `int | None` → `list[int]` (모든 청크 id). 호출자는 `ids[-1] if ids else None`로 pin용 마지막 id 획득(기존 호출처 호환).
- `reply_hook`: `for mid in sent_ids: store_reply_map(data_dir, mid, info.number)`. 모든 청크 → 동일 슬롯 매핑.
- `pin_board`/다른 `send()` 호출처는 `sent_ids[-1]`만 쓰면 됨(마지막 id = pin 대상).

**하위 호환**: 단일 전송은 길이 1 리스트. `None`은 빈 리스트와 동등 취급.

### 13.3 `/doctor` 진단 명령

**배경**: public repo 사용자가 "왜 안 되지?" 자가진단. install 지원 부담 ↓. design 12.x(부팅함정/stale slot) 이슈와 직결.

**설계**: `commands/doctor_command.py`. 각 항목 ✅/⚠️/❌ + 한 줄 설명 → 텔레그램 전송.

검사 항목:
1. **router heartbeat** — `data_dir/heartbeat.txt` age < 30s (alive) / < 120s (지연) / 그외 (죽음/미기동).
2. **registry 슬롯** — active 수 + 상태별(idle/busy/dead 카운트).
3. **pin 메시지** — `data_dir/pin.json`(또는 board status_id) 존재 여부.
4. **CC 훅 설치** — `~/.claude/settings.json`에 imadhd 4 훅(SessionStart/Stop/PreToolUse/UserPromptSubmit) 존재.
5. **pm2 router** — `pm2 jlist`에 `imadhd` online. + 부팅 autostart(startup 등록 여부 — Windows: resurrect.cmd+schtasks, Linux: systemd).
6. **bot command scope** — getMyCommands default + all_private_chats 양쪽에 ImADHD 명령 존재(메뉴 안 뜨면 scope 누락).

출력 포맷(예시):
```
🔍 ImADHD doctor
✅ router: alive (heartbeat 5s)
✅ slots: 3 active (2 idle, 1 busy)
✅ pin: 설정됨 (status=123, kb=124)
⚠️ hooks: 3/4 (UserPromptSubmit 누락)
✅ pm2: imadhd online
❌ bot menu: all_private_chats scope 비어있음 — install 재실행 권장
```

**의존**: telegram client(token 필요) → doctor 명령은 router 컨텍스트에서 실행(이미 token 로드됨). 단독 CLI 모드도 옵션(`python -m imadhd.cli doctor`).

---

## 14. v0.3.1 — pipe_win 전환 + 회신 모델 개편 (2026-07-06)

포커스 강제 없는 주입(named pipe + ConPTY)을 Windows 기본으로 올리고, 회신 라우팅을 마커 의존에서 **pending 플래그 + 길이 게이트**로 전면 개편. 위 4.3 / 4.4 / 4.6 / 4.6b / 4.7 의 구버전 설명(포커스 강제 send_keys, 주입 프롬프트에 마커 부착 + Stop 훅 마커 감지, CLAUDE.md 마커 규칙)은 **본절로 대체**.

### 14.1 pipe_win — focus-less named-pipe 주입 (Windows 기본)

**문제**: sendkeys_win(4.6)은 주입 전 대상 창을 포그라운드로 강제(`SetForegroundWindow`)해야 함 → 주입마다 **포커스 탈취**. 다른 창을 보고 있으면 방해.

**해결 — PTY-bridge (`imadhd/host.py`)**:
- 터미널을 `host.py` 아래 띄움(14.3). host.py 가 ConPTY(`pywinpty`) 생성 → Claude Code 를 PTY 자식으로 spawn.
- host.py 는 두 입력을 PTY 에 mux:
  1. **키보드** — 실제 타이핑 정상 동작.
  2. **named pipe** `\\.\pipe\imadhd-slot-<N>` — router 주입 채널.
- **와이어 프로토콜**: router 클라이언트가 UTF-8 `payload + b"\n"` 기록 → host.py 가 `\n` 까지 버퍼링 → PTY 에 `payload + "\r"` 기록(CR = TUI Enter).
- 포커스 전환 無. 터미널이 백그라운드여도 입력 도달.

**폴백**: 파이프가 없거나(수동 `claude` 실행 = bridge 無) 연결 실패 → `PipeWinTransport` 가 `SendKeysWinTransport` 로 투명 위임(`debug.log` 에 `focus hwnd=… SetFG=1 match=True` 로 확인 가능).

**진단**: host.py 생명주기 → `repo/_host_diag.log`(`host start slot=N`, `pipe OK`, `pipe CONNECTED`). 이 로그가 안 쓰이면 bridge 미기동(수동으로 연 터미널).

커밋: `7472b75`(도입), `21f80b0`(예외 처리 + 진단).

### 14.2 회신 모델 — pending 플래그 + 길이 게이트 (마커 의존 제거)

**구모델(제거)**: router 가 주입 프롬프트 말단에 `[A.D.H.D]` 마커 부착 → CLAUDE.md 규칙이 CC 에게 "마지막 줄에 마커 출력" 지시 → Stop 훅이 echo 감지 → 회신. 문제:
- CC 가 규칙을 **잊으면** 회신 자체가 안 감(작업은 끝났는데 회신만 유실되는 silent failure).
- 더 심각: CC 가 **직접 타이핑 턴**에 마커를 과잉 출력하면 → 텔레그램으로 새어나감(2026-07-06 session=`c4f60955` 실측).

**신모델**:
1. **주입 시** `inject_command.mark_marker_pending()` → `~/.imadhd/marker_pending/<session_id>` 파일 작성(내용 = 타임스탬프). 이 턴이 텔레그램 기원임을 나타내는 **유일 ground-truth 신호**. (함수명은 legacy 유지, 실제 의미는 '회신 대상 턴' 플래그.)
2. **Stop 시** `reply_hook`:
   - **플래그 無 → 비텔레그램 턴 → suppress**. 회신도 `block` 도 안 함. 직접 타이핑은 로컬에만 머뭄. (CLAUDE.md 규칙 삭제, 프롬프트에 마커 無, CC 는 텔레그램 인입 사실을 완전히 모름.)
   - **플래그 有 + assistant 답 有 → 회신 턴**. 길이 게이트 통과 시 전송.
   - **플래그 有 + 답 空 → 플래그 클리어, 전송 無**.
3. **길이 게이트**: `REPLY_HARD_LIMIT`(1200자) 초과 + 재시도 아님(`stop_hook_active=False`) → 1회 "결론 먼저 700자 이하로 다시" `block`. 재시도 턴(`stop_hook_active=True`)이면 전체 전송(청크 분할로 감당). 두 번은 안 막음.

`IMADHD_REPLY_MARKER` 는 **legacy 보조 신호**로만 잔존(구 inject 경로용). `MarkerCapture` 는 assistant 본문 전체를 반환(마커 잘라내기 불필요 — 주입 자체를 안 하므로).

플래그 파일 TTL = `MARKER_PENDING_TTL_SEC`(1h). 죽은 세션 잔재는 읽기 시 제거.

커밋: `b80c890`.

### 14.3 `/open` host wrapping

`/open` 이 **pipe-capable** 터미널을 엶: `claude` 직접 대신 `host.py` 로 감싸 띄움. CC 작업 cwd = 사용자 홈(IMADHD_CC_CWD) — host.py 모듈 해석은 repo, CC 는 홈에서 시작해 홈 기반 프로젝트/세션 인식.

Windows(detached, Windows Terminal 경유):
```
cmd.exe /c "cd /d <repo> && <py> -X utf8 -m imadhd.host -- claude [--model <m>]"
```
host.py 가 `--` 이후를 PTY 자식 명령으로 받아 ConPTY + named pipe 서버 기동. SessionStart 훅이 슬롯 클레임 → router 가 타겟 가능.

(수정 전엔 `/open` 이 `claude` 를 직접 실행 → bridge/파이프 無 → pipe_win 이 항상 sendkeys_win 으로 폴백. 14절 도입 전의 실제 증상이었음.) 커밋: `a4d96f4`.

### 14.4 config — .env authority (ambient env 무시)

**사고(2026-07-06)**: pm2 daemon / 터미널 부모 체인에 `IMADHD_TRANSPORT=sendkeys_win` 이 세션 레벨로 깔려 있었음(persistent store 어디에도 없음 — Windows user/machine env, `settings.json`, shell profile 전부 깨끗한데 live 프로세스 트리엔 존재). `load_dotenv(override=False)`(기본값) → `.env` 의 `pipe_win` 이 무시되고 sendkeys 로 회귀.

**수정**: `config.Settings.load()` 가 `~/.imadhd/env` 와 `repo/.env` 를 모두 `override=True` 로 로드. 의도된 config 가 ambient env 를 이김. 8b 절의 기존 설계 의도(settings.json global env 확산 방지)와 일치. 커밋: `56cf4e3`.

---

## 15. v0.3.2 — 텔레그램 명령 4종 + 안정성 (2026-07-06)

모바일에서 자기갱신·CC 버전업·위험도구 승인·이미지 양방향. 파이프 복원 근본원인 수정 동반.

### 15.1 `/update-adhd` — ImADHD 자기 갱신

**배경**: git pull → pytest → pm2 restart 3단계가 터미널 수동. 텔레그램 한 줄로.

**설계** (`commands/update_adhd_command.py`):
1. 답장 먼저(restart 가 자기 kill 전 flush 보장).
2. `git rev-list --left-right --count HEAD...origin/main` 로 behind 확인. 0이면 "이미 최신" 답장 후 종료.
3. `git pull --ff-only origin main`(shell=True 문자열 — install.py/watchdog.py 패턴 준수, npm global .CMD 이슈 동일).
4. `py -m pytest -q`(timeout 300s). 실패 시 restart **중단** + 결과 요약 답장(끊긴 코드로 restart 방지).
5. 답장 "✅ 코드 갱신 완료, 3초 후 restart".
6. **분리 지연 restart**: `subprocess.Popen('cmd /c "timeout /t 3 /nobreak >nul & pm2 restart imadhd"', DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP, close_fds=True)`. 3초 지연 = 답장 flush + 핸들러 정상 종료 시간. detach = 부모(router) 죽어도 restart 진행(사고5 boot_check 동일 패턴).

`TRIGGERS = {"/update-adhd", "/업데이트-adhd"}`. 커밋: `2a48b89`.

### 15.2 `/update` — CC 버전업 주입

**배경**: CC 버전업도 터미널 직접. 텔레그램에서 한 줄.

**설계** (`commands/update_cc_command.py`): `inject_command.do_inject()` 직접 재사용(slot 해석 + alive 체크 + grace wait + busy 표시 + marker_pending 전부 포함). 주입 텍스트 = `!claude update`. active 0 → "❌ 열린 CC 없음" 답장.

`TRIGGERS = {"/update", "/업데이트"}`. `InjectCommand.SLASH_RE = ^/([1-9])(?!\d)`(`/1`~`/9`만 매치) → `/update` 충돌 none. router commands 리스트 순서: InjectCommand **앞**에 등록(안전). 캐비어트: `claude update` silent-fail 리포트(GitHub #5494) — 단순주입 유지, 실패 시 폴백은 터미널 직접 `npm i -g @anthropic-ai/claude-code@latest`. 커밋: `2a48b89`.

### 15.3 도구승인 → 텔레그램 Yes/No (`perm_hook`)

**배경**: CLAUDE.md critical-ops 사전승인 정책(rm/drop/kill/disable/restart·git push 등). 위험 도구 실행 전 텔레그램 승인.

**설계** (`hooks/perm_hook.py`, PreToolUse matcher `Bash|Write|Edit`):
- 청사진 = `ask_hook` + `ask_manager` 복제. callback_data prefix `p:`(perm) vs `a:`(ask)로 분리.
- **위험 분류** `classify_risk`: Bash `tool_input.command` regex 25종 매칭(`rm`/`del`/`git push|reset --hard|clean|force`/`kill`/`pm2 delete`/`sudo`/`drop|truncate`/`systemctl`/`format`/`shutdown`/`Remove-Item` ...). Write/Edit = 보호디렉토리(CLAUDE.md bot-runtime-dirs + settings.json 보호경로) 매칭만 게이트.
- 매칭 안 됨 → **즉시 `permissionDecision:allow` emit + return**(텔레그램 미송신, 지연 0).
- 매칭 → inline Yes/No 버튼 송신(`perm_manager.build_inline_keyboard(perm_id)`). 본문 = `⚠️ <tool>: <요약>`.
- 280s 폴링 + router heartbeat 40s stale 시 조기 timeout. 응답 도착 → `allow`/`deny` emit. **timeout → deny**(안전, 정직). timeout 메시지 텔레그램 송신.
- 마커 게이트(터미널 직접 작업 = skip — CC 네이티브 처리). fail-open.

**bypassPermissions 연동** (실증 2026-07-06, 공식문서 확정): CC `defaultMode:"bypassPermissions"` 에서도 PreToolUse 훅 `permissionDecision:deny` 가 비인터랙티브 도구(Bash)를 **실제 차단**. 훅이 permission-mode 체크 이전에 발화, 우선순위 `deny>defer>ask>allow`. 캐비어트: Edit 툴 deny 무시 버그(GitHub #37210) — Edit 경로는 게이트가 완전하진 않음(차단 보장 아님).

커밋: `2a48b89`. 라이브 검증: 임시 transcript(마커)+stdin 시뮬 → perm_hook 발동 → TG Yes/No 송신 → 대표님 Yes 클릭 → router callback → perm 기록 approved → 훅 폴링 감지 → `permissionDecision:allow` emit 실측.

### 15.4 이미지 양방향

**CC→TG** (`telegram_api/client.py:send_photo` + `hooks/reply_hook.py`):
- CC transcript assistant content 의 image 블록 = Anthropic SDK 표준 `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"<b64>"}}`(URL 타입도 스펙상 가능하나 CC 생성 이미지는 base64).
- `reply_hook._extract_images`: base64 디코딩 → raw bytes + ext(png/jpg). `_last_assistant_images`: 마지막 assistant entry 에서 image 추출(text 와 같은 entry 공존 가능).
- `client.send_photo`: multipart/form-data **수동 인코딩**(`_build_multipart`, urllib + boundary 조립, **의존성 0** — requests 안 씀). caption 1000자 절단(sendPhoto 4096 한도 400 방지). text 회신과 **별도 메시지**, 같은 slot reply_map 매핑(image 답장해도 번호 라우팅 적중).
- 마커 턴에만 송신(pending 플래그). 캐비어트: reply_hook Stop 훅 timeout 15s(settings.json) vs 큰 이미지 업로드 60s — text 는 먼저 flush 되므로 **회신 유실 X, image 만 유실 가능**(debug_log 남김). 작은 이미지(수백KB)는 15s 내 OK.

**TG→CC** (`core/router.py:_handle_photo` + `client.download_file`):
- incoming `message.photo`(size 배열) → 가장 큰 size `file_id` → `client.download_file`(getFile API → file_path → 다운로드) → `~/.imadhd/inbox/tg_<fileid>.jpg` 원자쓰기(tempfile+os.replace).
- 활성 CC 에 `이미지 수신: <path>` 주입 + marker_pending(회신 대상 턴 플래그). CC 가 경로를 Read 해 분석. active 0 → "❌ 열린 CC 없음" 답장.

커밋: `2a48b89`(TG→CC 수신부 download_file + _handle_photo) + `fa499a7`(CC→TG 송신부 send_photo + reply_hook image).

### 15.5 안정성 — 파이프 복원 근본 + 좀비 감시

- **파이프 복원 B 근본** (`b6b3cda`): slot 기반 → **host_pid 기반** 매칭. slot 번호가 바뀌어도 host.py pid 로 파이프 경로 역추적. 근본원인 수정(임시 patch 아님 — 앞선 f8c8fd3 CP949/파이프 patch 의 근본).
- **`/open` 단일화 + io_utils** (`f2fc24e`): /open 분기 단순화 + 원자쓰기/읽기 `core/io_utils.py` 공통 모듈화(ask_manager·perm_manager·reply_map 등 중복 제거).
- **pm2 zombie boot_check** (`972be2d`): pm2 좀비(online 상태인데 pid 없) 1차 방어. resurrect 시 자동 복구.
- **sync_alive self-heal** (`1125c87`): router 런타임에 CC 생사 재활 → registry 와 live CC 동기화(stale slot 자동 정리, 오판 사고 방지).
- **`/open` host wrapping 제거→복귀** (`7ae1792` → 14.3 유지): 직접 spawn 시도 후 pipe_win 폴백 만능 아님 판명, host wrapping 유지로 회귀.

### 15.6 검증

- pytest **308 passed**(회귀 없음).
- 라이브 end-to-end: F3 perm `allow` emit(대표님 Yes 클릭) / F4 CC→TG `send_photo ok`(1x1 PNG, bytes=70) / F4 TG→CC inbox 35KB JPEG 저장 + CC 경로 주입 + Read 표시.
- 재부팅 후 부팅 자동시작 + 회신 라운드트립 통과(대표님 실측 2026-07-06).

