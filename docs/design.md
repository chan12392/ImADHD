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
