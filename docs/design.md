# 백호-텔레그램 다중터미널 라우터 — 설계 spec

- 작성: 2026-07-02
- 작성자: 백호 (데스크톱 비서)
- 상태: 승인됨 (구현계획 대기)

---

## 1. 목표

대표님이 **외부에서 텔레그램 DM 하나**로, 데스크톱에 띄워둔 **여러 Claude Code(백호) 세션 중 하나를 골라 작업 지시**하고 답변을 받는다.

- 기본은 터미널 직접 소통. 텔레그램은 "외출 시 이어가기"용.
- 하나의 텔레그램 봇 = 여러 CC 세션(최대 6) 라우팅.
- 각 세션은 번호(1~6)로 구분. **가장 먼저 띄운 CC = 1번**, 다음 = 2번 …
- DM 앞에 숫자 이모지(`1️⃣`~`6️⃣`)가 없으면 아무 세션도 반응 안 함.

## 2. 핵심 원칙

**CC는 텔레그램을 직접 모른다.** pm2 폴링 데몬(tg-router)이 유일하게 텔레그램과 통신하고, CC에게는 `send_keys` 키 주입으로 요청을 전달한다. CC의 답변은 Stop 훅이 transcript에서 캡처해 텔레그램으로 회신한다.

→ CC 본체 변경 최소화. 기존 `send_keys_to_claude.py`, 텔레그램 봇 토큰, pm2, python 인프라 전부 재사용.

## 3. 아키텍처

```
                 ┌───────────────────────────┐
   대표님  ──DM──▶│  Telegram Bot (백호 봇)    │
   (외부)         └─────────────┬─────────────┘
                               │ getUpdates (롱폴)
                 ┌─────────────▼─────────────┐
                 │  pm2: tg-router.py (라우터) │
                 │  - 숫자이모지 파싱          │
                 │  - registry 조회           │
                 │  - 사전체크(IsWindow/pid)  │
                 │  - ack 텔레그램 전송        │
                 └─────┬───────────────┬──────┘
        주입(send_keys)│               │ 회신(Bot API)
                       │               │
        ┌──────────────▼──┐    ┌───────▼──────────────┐
        │ send_keys       │    │ Stop 훅              │
        │ (포커스→타이핑) │    │ tg-reply-capture.py  │
        └──────────────┬──┘    │ - transcript 읽기    │
                       │       │ - 마커 감지          │
            ┌──────────▼────┐  │ - session_id→번호   │
            │  CC-N 세션    │──┘ - 답변 텔레그램 전송 │
            │ (백호-N)      │
            └───────────────┘

   registry.json ◀── 등록: SessionStart 훅 tg-register.py
     {번호: {session_id, hwnd, pid, cwd, started_at}}
```

## 4. 컴포넌트

### 4.1 registry.json (런타임 상태)
- 경로: `$HOME/.claude/baekho-tg/registry.json`
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

### 4.2 SessionStart 훅 — `tg-register.py`
- 위치: `$HOME/.claude/scripts/tg-register.py`
- 역할: CC 세션 시작 감지 → 빈 번호 클레임 → registry 등록.
- 절차:
  1. stdin payload에서 `session_id`, `cwd` 확보.
  2. registry 잠금 → 가장 낮은 빈 번호(1~6) 선택. 6개 꽉 차면 `7` 이상 거부 + 텔레그램 경고.
  3. `GetForegroundWindow()` 로 현재 터미널 HWND 캡처 (CC 시작 직후 포커스 = 이 터미널).
  4. pid(현재 프로세스 또는 부모) 기록.
  5. registry 갱신 해제.
  6. 텔레그램 알림: `✅ N번 터미널 연결됨 (PID xxxx, cwd)`.
- 동일 session_id 재시작 시 기존 슬롯 재사용(덮어쓰기).

### 4.3 pm2 폴링 데몬 — `tg-router.py`
- 위치: `$HOME/.claude/scripts/tg-router.py`
- pm2 이름: `baekho-tg`
- 역할: 텔레그램 롱폴 → 라우팅 → 주입.
- 절차:
  1. `getUpdates(offset)` 롱폴. offset 은 `$HOME/.claude/baekho-tg/offset.txt` 에 영구 저장(pm2 재시작 시 중복 처리 방지).
  2. 메시지 본문 선두의 숫자이모지(`1️⃣`~`6️⃣`) 파싱.
     - **없으면 무시** (아무 반응 안 함).
     - 단 예외 명령(번호 없이): `/터미널` → 현재 registry 활성 목록 전체 전송.
  3. 번호 → registry 조회.
  4. **사전체크** (리스크2 완화):
     - `IsWindow(hwnd)` + pid 프로세스 생존 확인.
     - 죽었으면 → registry 해당 슬롯 `null` 처리 → 텔레그램 `❌ N번 터미널 꺼져있음` → 입력 중단.
  5. 살았으면 ack 전송: `📩 N번 ← <본문 요약>`.
  6. `send_keys_to_claude.py --hwnd <hwnd> --text "<본문>\n\n[텔레그램에서 온 요청. 답변 끝에 '텔레그램으로 답변' 문구를 출력할 것]"` 실행.
     - 입력: 기본 **포커스 강제** (v1). `--bg` 옵션 시 베타 백그라운드 시도 (리스크3).
  7. 다음 offset 으로 갱신.

### 4.4 Stop 훅 — `tg-reply-capture.py`
- 위치: `$HOME/.claude/scripts/tg-reply-capture.py`
- 역할: CC 응답 종료 시 답변 캡처 → 텔레그램 회신.
- 기존 `channel-reply-guard.py`(Stop 훅)과 **별도 추가**, 공존.
- 절차:
  1. stdin payload에서 `session_id`, `transcript_path` 확보.
  2. transcript JSONL 의 마지막 assistant 메시지 본문 읽기.
  3. 본문 말단에 `텔레그램으로 답변` 마커 있는지 확인.
     - 없으면 종료 (일반 터미널 응답 → 회신 안 함).
  4. 있으면 → 마커 **제거한 본문** 추출.
  5. registry 역조회: `session_id → 번호`.
  6. 해당 번호 숫자이모지를 본문 앞에 붙여 텔레그램 전송. (번호 못 찾으면 그냥 전송.)
  7. `stop_hook_active=True` 면 통과(무한루프 방지).

### 4.5 send_keys 확장 — `send_keys_to_claude.py`
- 위치: `$HOME/programs/send_keys_to_claude.py` (기존, 확장)
- 추가 기능:
  - `--hwnd <핸들>` 옵션: 번호로 창 찾는 대신 HWND 직접 지정.
  - `--bg` 옵션(**베타, 기본 off**): 백그라운드 입력(PostMessage WM_CHAR/WM_KEYDOWN) 시도.
    - **도달 보장 없음**: PostMessage는 입력이 실제로 도달했는지 반환하지 않음. Windows Terminal 자식창 겹겹 구조라 일부 창에만 닿음.
    - 실패 감지 불가 → 폴백 트리거 애매 → v1은 **기본 포커스 강제**로 확실 입력 보장.
    - 추후 conpty 기반 안정 메커니즘 확보 시 `--bg` 기본 전환 검토.
- 기존 `--title` 인터페이스(telegram-new-command 호환) 유지.
- 기본 동작(옵션 없음) = HWND 찾아 포커스 강제 후 타이핑 (v1 기준).

### 4.6 백호 CLAUDE.md 규칙 추가
`$HOME/.claude/CLAUDE.md` 의 절대규칙 블록에 추가:
> **텔레그램 요청 응답 규칙**: 프롬프트에 `[텔레그램에서 온 요청]` 표시가 있으면, 최종 답변의 **마지막 줄에 반드시 `텔레그램으로 답변` 문구 출력**. (Stop 훅 회신 트리거.)

## 5. 데이터 흐름 (정상 케이스)

```
[대표님 텔레그램] "3️⃣ 빌드 로그 확인해줘"
  → getUpdates
  → 번호=3, 본문="빌드 로그 확인해줘"
  → registry: 3 → {hwnd_3, pid_3}
  → 사전체크: IsWindow(hwnd_3)=true, pid_3 살음
  → ack 텔레그램: "📩 3번 ← 빌드 로그 확인해줘"
  → send_keys --hwnd hwnd_3 (포커스 강제) → 타이핑:
      "빌드 로그 확인해줘
       [텔레그램에서 온 요청. 답변 끝에 '텔레그램으로 답변' 출력]"
      ENTER
  → CC-3 백호 정상 처리
  → CC-3 답변: "...로그 분석 결과...\n\n텔레그램으로 답변"
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
| 동일 session_id 재시작 | 기존 번호 슬롯 덮어쓰기 |
| 6개 꽉 찬 상태서 시작 | 거부 + 텔레그램 경고("모든 슬롯 사용 중") |
| 대표님 `/터미널` | 현재 활성 registry 목록 텔레그램 전송 |

## 7. 리스크 & 완화

1. **포커스 강제 전환** — N번 주입 시 N번 창이 화면에 튀어나옴.
   - 대표님 수용 (외출 시나리오에서는 무방).
   - 완화: 백그라운드 입력 우선 시도(리스크3)로 가능한 한 포커스 안 빼앗음.
2. **registry 스테일 슬롯** — send_keys **직전 사전체크**(IsWindow + pid)로 회수. (대표님 제안 채택)
3. **HWND 백그라운드 입력 불안정** — Windows Terminal 자식창 겹겹 구조. PostMessage 는 도달 여부 미반환 → **실패 감지 불가**.
   - 정직성 정정: **v1 기본 = 포커스 강제**(확실). `--bg` 는 베타 옵션(시도만, 도달 보장 X). "백그라운드 된다" 과장 안 함.
   - 추후 conpty/pty 기반 안정 메커니즘 확보 시 기본 전환 검토.
4. **포커스 경합** — 동시 다번호 주입 시 포커스 튕김.
   - 완화: tg-router 내부 큐 직렬 처리.
5. **pm2 orphan / offset 중복** (mem0 교훈) — offset.txt 영구 저장 + pm2 재시작 전 pid/포트/코드경로 함께 확인.

## 8. 파일 레이아웃 (모듈 패키지)

**독립 프라이빗 레포 + pip 패키지 구조.** 기능 추가 시 해당 모듈만 추가/변경, core 안 건드림.

```
baekho-tg/                          # 레포 루트 (git private)
├── pyproject.toml                  # 패키지 정의 + entry_points
├── README.md                       # 퍼블릭용: 설치/설정/사용법
├── LICENSE                         # MIT
├── .gitignore                      # .env, __pycache__, *.json(런타임), offset
├── .env.example                    # TELEGRAM_BOT_TOKEN= (예시만, 실값 X)
├── CHANGELOG.md
├── docs/
│   └── design.md                   # 본 spec
└── baekho_tg/                      # 패키지
    ├── __init__.py
    ├── config.py                   # 설정 로드: env/.env → 데이터객체 (시크릿 여기서만)
    ├── core/
    │   ├── registry.py             # 번호↔세션 매핑 (Registry 인터페이스 + JSONFile impl)
    │   ├── numberalloc.py          # 빈 슬롯 할당 정책
    │   └── router.py               # 텔레그램 폴링 + 라우팅 메인루프
    ├── transports/                 # ★확장포인트1: 터미널 입력 방식
    │   ├── base.py                 # Transport ABC: inject(target, text) -> bool
    │   ├── sendkeys_win.py         # Windows ctypes send_keys (기본, --hwnd/--bg)
    │   └── (future: tmux.py / pty.py)
    ├── commands/                   # ★확장포인트2: 텔레그램 명령
    │   ├── base.py                 # Command ABC: match(msg)->bool, handle(...)
    │   ├── inject_command.py       # N️⃣<본문> → 사전체크 → 주입 → ack
    │   └── list_command.py         # /터미널 → 활성 목록
    ├── reply/                      # ★확장포인트3: 답변 회신
    │   ├── base.py                 # ReplyStrategy ABC
    │   └── marker_capture.py       # Stop 훅 마커 감지/추출
    ├── hooks/                      # CC 훅 (settings.json 에서 호출)
    │   ├── register_hook.py        # SessionStart: 번호할당/HWND캡처/등록
    │   └── reply_hook.py           # Stop: 답변 캡처/회신
    ├── telegram_api/
    │   └── client.py               # Bot API 래퍼 (getUpdates/sendMessage, offset 영구)
    └── cli.py                      # entry_points: btg-router / btg-register / btg-reply
```

**확장 시나리오 (기능 추가 빠르게):**
| 추가 기능 | 작업 | core 변경 |
|---|---|---|
| 새 입력방식(tmux) | `transports/tmux.py` + config 등록 | 없음 |
| 새 명령(/상태) | `commands/status.py` + 등록 | 없음 |
| discord 회신 | `reply/discord.py` + `telegram_api/` 형태 추가 | 없음 |
| 번호할당정책 변경 | `numberalloc.py` 교체 | 없음 |

## 8b. 퍼블릭 전환 대비 (시크릿 분리)

- **모든 시크릿 = 환경변수 또는 `.env`** (gitignore). `config.py` 에서만 로드. 코드/커밋에 토큰 절대 금지.
- `.env.example` = 키 이름만(값 비움).
- registry.json / offset.txt = 런타임 상태 → gitignore. 예시는 `examples/`.
- 봇 토큰(백호 봇)은 대표님 로컬 `.env`에만. 퍼블릭 레포엔 없음.
- git history clean 유지: 초기 커밋부터 시크릿 없음 (나중에 공개 전 `git log -p | grep 토큰` 점검).
- Windows 전용 기능(sendkeys) → README에 플랫폼 명시, transports 인터페이스로 타OS 확장 열어둠.

## 9. settings.json 훅 등록

- `SessionStart`: `tg-register.py` 추가 (matcher: startup).
- `Stop`: `tg-reply-capture.py` 추가 (기존 `channel-reply-guard.py` 유지, 별도 엔트리).
- 기존 `telegram-new-command.py`(UserPromptSubmit)는 채널 래퍼 인입만 매칭 → 우리 send_keys 타이핑은 채널 래퍼 없음 → **충돌 없음, 유지**.

## 10. 구현 순서 (요약, 상세는 writing-plans)

1. 디렉토리 + registry.json 초기화(offset 6슬롯 null).
2. `tg-register.py` (SessionStart) — 번호 할당/HWND 캡처/등록.
3. `send_keys_to_claude.py` 확장 — `--hwnd`, `--bg`.
4. `tg-router.py` (pm2) — 폴링/파싱/사전체크/주입/ack.
5. `tg-reply-capture.py` (Stop) — 마커 감지/본문 추출/회신.
6. settings.json 훅 2개 등록.
7. CLAUDE.md 규칙 추가.
8. pm2 `baekho-tg` 시작 + 수동 E2E (대표님 텔레그램 → CC 1~2개 띄워서 번호 라우팅/회신 검증).

## 11. 미해결 / 추후

- HWND 캡처 타이밍: SessionStart 실행 시점과 실제 터미널 창 포커스 시점 차이 → prewait + 재시도 폴백.
- 백그라운드 입력 감지 신뢰성: Windows Terminal 버전별 차이 → 실패 시 즉시 폴백 보장.
- CC 정상 종료 감지: SessionEnd 훅 부재 → 사전체크 의존. 필요시 하트비트(각 CC 주기적 ping) 추가 가능.

---

## 12. 상태 보드(ReplyKeyboard) + 선택 모드

> 추가: 2026-07-03. 대표님 UI 요구 진화에 따른 보드 형태 + 주입 흐름 개편.

### 12.1 배경 — 보드 형태 결정 과정

터미널 상태(⭕ idle / 📝 busy / ❌ dead) 시각화를 어디에 둘지 대표님 요구 진화:

1. 번호+마크 형태(`1️⃣⭕ 2️⃣❌ …`) 요청 → 인라인 키보드 핀 구현(메시지 #147).
2. "입력창 위에 영구 떠있게" → 핀(상단 고정) 배치 시도.
3. "입력창 위 말고 사진처럼 떠야 할 듯" → 사진 재해석 요청.
4. **"사진은 햄버거 메뉴가 아님, 입력창 아래에 통합된 버튼"** → 정정.
   → 실제 의도 = **ReplyKeyboardMarkup**(입력창 아래 영구 커스텀 키보드, 버튼 3열 그리드).

> 이미지 분석 도구(mcp `analyze_image`)는 사진을 "햄버거 사이드 메뉴 drawer"로 3회 오독. 대표님 정정으로 ReplyKeyboard 확정. **교훈: 해당 도구 신뢰 낮음, 로컬 재확인 또는 대표님 확인 우선.**

### 12.2 텔레그램 API 제약 (조사 결과)

대표님 후속 요구 "버튼 클릭 → 입력창에 숫자만 채우기(전송 X)":

| 시도 | 결과 |
|---|---|
| **ReplyKeyboardMarkup** | 버튼 클릭 = 무조건 **즉시 메시지 전송**. 입력창 채우기 불가. |
| **봇이 사용자 입력창 직접 조작** | 보안상 API 미지원 (Latenode/Telegram 문서 확인). |
| **switch_inline_query_current_chat** | 입력창에 `@봇유저네임 <query>` 채워지나 **inline mode 진입** → 본문 전송 흐름 깨짐(결과 패널만 표시) + 봇멘션 동반. |

→ "버튼 클릭 → 입력창만 채우기"는 **불가능** 확인.

### 12.3 채택 — 선택 모드 (ReplyKeyboard + 핀 고정 + 흔적 최소화)

대표님 결정: **ReplyKeyboard(입력창 아래) + 보드 메시지 상단 핀 고정 + 실시간 갱신 + 클릭 흔적 최소** (옵션 A).

- 보드 메시지(상태 텍스트 + ReplyKeyboard)를 **상단 핀 고정**(`pinChatMessage`). 스크롤에 안 묻힘.
- 상태 변 시 **본문 + 키보드 둘 다 실시간 갱신**(`editMessageText`에 `reply_markup` 포함). 마크(⭕📝❌) 즉시 반영.
- 버튼 텍스트/상태 텍스트 포맷: 번호이모지와 마크 사이 **점(`.`) 구분** → `1️⃣.⭕`. (숫자와 상태 시인성 분리.)
- 버튼 클릭(번호+점+상태마크) → **선택모드 대기**(pending) 등록. **안내 메시지 생략**.
- **대기 토글**: 같은 번호 재클릭 → 대기 취소. 다른 번호 클릭 → 대기 번호 교체. (대표님 요청 "한 번 더 누르면 취소, 다른 번호 누르면 변경".)
- 다음 본문 메시지(번호 없음) → 대기 번호로 주입(**300초(5분) TTL**).
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
- `PENDING_TTL = 300` 상수(5분).

**CommandContext** (`imadhd/commands/base.py`):
- `pending: dict` 필드 추가(`field(default_factory=dict)`). `chat_id → (num, timestamp)`.

**router** (`imadhd/core/router.py`):
- 메시지 루프: 번호 없는 본문 + `ctx.pending` 있으면 → TTL 내 `do_inject` 주입 + pending 소비. 만료 시 pending 삭제 후 일반 명령으로 폴백.
- callback_query 핸들러 제거(ReplyKeyboard는 callback 안 옴).

### 12.5 데이터 흐름 (선택 모드)

```
[대표님] 1️⃣.⭕ 버튼 클릭
  → ReplyKeyboard: "1️⃣.⭕" 메시지 즉시 전송 (채팅에 1줄 남음)
  → router: InjectCommand.match → handle
  → body=".⭕" → 점 제거 → "⭕"(상태마크)
  → ctx.pending 미사용 → pending["chat"]=(1, ts). 안내 생략.
[대표님] "로그 확인해줘" (번호 없음)
  → router: parse_leading_number=None + pending 있음 + TTL(300s) 내
  → do_inject(ctx, 1, "로그 확인해줘", chat)
  → CC-1 주입: "로그 확인해줘 [텔레그램에서 온 요청]"
  → pending 소비. CC 답변 마커 → Stop 훅 회신.

[토글] 대기 중 같은 번호 재클릭(1️⃣.⭕) → pending 삭제(대기 취소).
[교체] 대기 중 다른 번호 클릭(2️⃣.⭕) → pending[chat]=(2, ts) 교체.
(300초(5분) 경과 본문 없음 → pending 자동 해제)
```

### 12.6 트레이드오프 결정 기록

| 옵션 | 채택 | 이유 |
|---|---|---|
| ReplyKeyboard(입력창 아래) + 선택모드 | ✅ | 대표님 "사진=입력창 아래 영구" + "흔적 작게" 동시 만족 가능선 |
| 인라인 핀 + callback(클릭 흔적 0) | ❌ | 채팅에 흔적 0이지만 버튼=상단 핀(입력창 아래 위배) |
| switch_inline_query_current_chat | ❌ | inline mode 진입, 본문 전송 흐름 깨짐 |

### 12.7 리스크 & 보완

1. **잘못된 터미널 주입**: pending 중 본문이 의도치 않은 메시지여도 주입됨.
   - 완화: TTL 300초(5분). 클릭 직후 바로 본문 치는 흐름 권장. **취소 토글**(같은 번호 재클릭)로 의도치 않은 대기 해제 가능.
2. **ReplyKeyboard 활성 갱신**: 핀 메시지를 `editMessageText`(본문+markup)로 갱신. Telegram이 마지막 `reply_markup` 메시지를 활성 키보드로 사용 → 보드 메시지가 최신이면 갱신 보장. 라이브 검증(터미널 시작/종료 시 마크 변경) 완료 필요.
3. **버튼 클릭 메시지 잔류**: `1️⃣.⭕` 1줄씩 채팅에 쌓임(ReplyKeyboard 불가피). 안내 회신 생략으로 줄 수 최소화.
4. **대기 상태 비가시성**: 안내 생략 정책상 대표님이 어떤 번호 대기 중인지 채팅에 표시 안 됨. 토글/교체 흐름이므로 메모리 기준. (필요시 보드 텍스트에 대기 번호 하이라이트 검토 가능.)

### 12.8 라이브 검증 체크리스트

- [x] 기존 인라인 핀(#147) → ReplyKeyboard(#154) 교체 (repin.py)
- [x] 47/47 테스트 통과 (선택모드 pending + 토글(취소/교체) + do_inject + 보드 ReplyKeyboard/핀/실시간)
- [x] pm2 `imadhd` 재시작 정상 기동 (에러 없음)
- [x] **대표님 폰 확인**: 입력창 아래 6개 버튼 표시 / 버튼 클릭 후 본문 시 주입 정상 (2026-07-03 라이브 — "잘 보여" 본문이 선택모드로 정상 주입됨 확인)
- [ ] 터미널 on-off 시 마크(⭕❌) 자동 변경 확인 (대기)
- [ ] 대기 토글(같은 번호 재클릭=취소 / 다른 번호=교체) 라이브 확인 (대기)
