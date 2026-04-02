# KIS AutoTrader

한국투자증권(KIS) OpenAPI 기반 주식 자동매매 시스템.
장중 자동 시세 조회, 전략 기반 매매, 리스크 관리, 일일 결과 Google Calendar 등록까지 자동화합니다.

## 주요 기능

- **자동 매매** — 이동평균 교차, RSI 전략 기반 자동 매수/매도
- **리스크 관리** — 최대 손실률 제한, 포지션 사이징, 일일 매매 횟수 제한, 손절/익절 자동 판단
- **실시간 시세** — 웹소켓 기반 실시간 호가/체결 수신 (상태 머신 + 자동 재연결)
- **API 안전장치** — Token Bucket Rate Limiter, Circuit Breaker, exponential backoff 재시도
- **스케줄링** — 장 시작 전 토큰 갱신 → 장중 주기적 매매 → 장 마감 후 결산 자동 실행
- **Google Calendar 연동** — 일일 매매 결과를 캘린더 이벤트로 자동 등록
- **DB 영속성** — PostgreSQL + SQLAlchemy ORM + Alembic 마이그레이션

## 기술 스택

| 구분 | 기술 |
|------|------|
| Language | Python 3.12+ |
| HTTP Client | httpx (async) |
| WebSocket | websockets |
| Database | PostgreSQL + SQLAlchemy 2.0 + Alembic |
| Scheduler | APScheduler |
| Data Analysis | pandas |
| Calendar | Google Calendar API |
| Test | pytest + pytest-asyncio |
| Lint/Type | ruff, mypy (strict) |

## 프로젝트 구조

```
kis-autotrader/
├── main.py                        # 엔트리포인트
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                  # 마이그레이션 스크립트
├── src/
│   ├── config.py                  # 환경변수/설정 통합 관리
│   ├── api/
│   │   ├── rate_limiter.py        # Token Bucket Rate Limiter
│   │   ├── auth.py                # OAuth 토큰 발급/자동갱신
│   │   ├── client.py              # HTTP 클라이언트 (재시도, Circuit Breaker)
│   │   ├── order.py               # 주문 API (매수/매도/정정/취소)
│   │   ├── quote.py               # 시세 조회 API (현재가, 일봉, 분봉)
│   │   ├── account.py             # 잔고/체결내역 조회
│   │   └── websocket.py           # 실시간 웹소켓 매니저
│   ├── strategy/
│   │   ├── base.py                # 매매 전략 추상 클래스 + Signal
│   │   ├── moving_average.py      # 이동평균 교차 전략
│   │   ├── rsi.py                 # RSI 기반 전략
│   │   └── risk.py                # 리스크 관리 모듈
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM 모델
│   │   ├── session.py             # DB 세션 관리
│   │   └── repository.py          # CRUD Repository
│   ├── scheduler/
│   │   └── jobs.py                # APScheduler 작업 정의
│   ├── calendar/
│   │   ├── google_auth.py         # Google OAuth2 인증
│   │   └── event.py               # 캘린더 이벤트 생성
│   └── utils/
│       ├── logger.py              # 로깅 설정
│       └── exceptions.py          # 커스텀 예외 클래스
└── tests/
    ├── test_api/                   # API 모듈 테스트 (5개)
    ├── test_strategy/              # 전략 모듈 테스트 (4개)
    ├── test_db/                    # DB/스케줄러 테스트 (3개)
    └── test_calendar/              # Calendar 테스트 (2개)
```

---

## 설치 및 설정

### 1. 사전 요구사항

- Python 3.12+
- Docker Desktop (PostgreSQL 컨테이너용)
- [한국투자증권 OpenAPI 신청](https://apiportal.koreainvestment.com/) 완료
- Google Cloud Console에서 Calendar API 사용 설정 + `credentials.json` 발급

### 2. PostgreSQL 실행

```bash
docker run -d \
  --name kis-postgres \
  --restart unless-stopped \
  -e POSTGRES_USER=kis_user \
  -e POSTGRES_PASSWORD=kis_password \
  -e POSTGRES_DB=kis_trader \
  -p 5432:5432 \
  -v kis-postgres-data:/var/lib/postgresql/data \
  postgres:16-alpine
```

### 3. 프로젝트 설정

```bash
# 가상환경 생성 및 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 환경변수 설정
cp .env.example .env
# .env 파일 편집 (아래 '환경변수 설정' 섹션 참고)

# DB 마이그레이션 적용
alembic upgrade head
```

---

## 모의투자 / 실전투자 설정

`.env` 파일의 `KIS_ENV` 값 하나로 모의투자와 실전투자를 전환합니다.

### 모의투자 (기본값)

```env
KIS_ENV=virtual
KIS_APP_KEY=모의투자용_앱키
KIS_APP_SECRET=모의투자용_앱시크릿
KIS_ACCOUNT_NO=모의투자_계좌번호
```

### 실전투자

```env
KIS_ENV=real
KIS_APP_KEY=실전용_앱키
KIS_APP_SECRET=실전용_앱시크릿
KIS_ACCOUNT_NO=실전_계좌번호
```

### 차이점 상세

| 항목 | `virtual` (모의투자) | `real` (실전투자) |
|------|---------------------|-------------------|
| REST API URL | `https://openapivts.koreainvestment.com:29443` | `https://openapi.koreainvestment.com:9443` |
| WebSocket URL | `ws://ops.koreainvestment.com:31000` | `ws://ops.koreainvestment.com:21000` |
| 주문 tr_id (매수) | `VTTC0802U` | `TTTC0802U` |
| 주문 tr_id (매도) | `VTTC0801U` | `TTTC0801U` |
| 앱키/시크릿 | 모의투자 전용으로 별도 발급 | 실전 전용으로 별도 발급 |

> **주의**: 모의투자와 실전투자는 앱키/시크릿이 **별도로 발급**됩니다. 한국투자증권 API 포털에서 각각 신청해야 합니다.

### 권장 운영 순서

1. **모의투자로 시작** — `KIS_ENV=virtual`로 전략 검증 및 시스템 안정성 확인
2. **로그 분석** — 매매 시그널, 주문 체결, 리스크 관리 동작을 충분히 확인
3. **실전 전환** — `.env`에서 `KIS_ENV=real`로 변경하고 앱키/시크릿/계좌번호를 실전용으로 교체
4. **소액으로 시작** — `MAX_POSITION_RATIO`를 낮게 설정하여 리스크 최소화

---

## Google Calendar OAuth2 인증 설정

매매 결과를 Google Calendar에 자동 등록하려면 OAuth2 인증이 필요합니다.

### Step 1. Google Cloud 프로젝트 생성

1. [Google Cloud Console](https://console.cloud.google.com/)에 접속
2. 상단의 프로젝트 선택 드롭다운 → **새 프로젝트** 클릭
3. 프로젝트 이름 입력 (예: `kis-autotrader`) → **만들기**

### Step 2. Google Calendar API 활성화

1. 좌측 메뉴 → **API 및 서비스** → **라이브러리**
2. "Google Calendar API" 검색 → 클릭 → **사용** 버튼 클릭

### Step 3. OAuth 동의 화면 구성

1. 좌측 메뉴 → **API 및 서비스** → **OAuth 동의 화면**
2. **User Type**: 외부 선택 → **만들기**
3. 앱 정보 입력:
   - 앱 이름: `KIS AutoTrader`
   - 사용자 지원 이메일: 본인 이메일
   - 개발자 연락처: 본인 이메일
4. **범위(Scopes)** 단계에서 **범위 추가 또는 삭제** 클릭:
   - `https://www.googleapis.com/auth/calendar.events` 선택
5. **테스트 사용자** 단계에서 본인 Gmail 주소 추가
6. **요약** 확인 후 완료

### Step 4. OAuth 클라이언트 ID 생성

1. 좌측 메뉴 → **API 및 서비스** → **사용자 인증 정보**
2. **+ 사용자 인증 정보 만들기** → **OAuth 클라이언트 ID**
3. 애플리케이션 유형: **데스크톱 앱**
4. 이름 입력 (예: `KIS AutoTrader Desktop`) → **만들기**
5. **JSON 다운로드** 클릭 → 프로젝트 루트에 `credentials.json`으로 저장

### Step 5. 캘린더 ID 확인

1. [Google Calendar](https://calendar.google.com/) 접속
2. 사용할 캘린더의 **설정 및 공유** → **캘린더 통합** 섹션
3. **캘린더 ID** 복사 (예: `abcdef1234@group.calendar.google.com`)
   - 기본 캘린더를 사용하려면 본인 Gmail 주소가 캘린더 ID입니다

### Step 6. .env 파일에 설정

```env
GOOGLE_CALENDAR_ID=abcdef1234@group.calendar.google.com
GOOGLE_CREDENTIALS_PATH=credentials.json
```

### Step 7. 최초 인증 실행

```bash
source .venv/bin/activate
python -c "from src.calendar.google_auth import GoogleCalendarAuth; GoogleCalendarAuth().authenticate()"
```

- 브라우저가 자동으로 열리며 Google 로그인 → 권한 승인을 요청합니다
- 승인하면 프로젝트 루트에 `token.json`이 자동 생성됩니다
- 이후 실행부터는 `token.json`으로 자동 인증되며, 만료 시 자동 갱신됩니다

> **주의**: `credentials.json`과 `token.json`은 `.gitignore`에 포함되어 있어 git에 커밋되지 않습니다. 절대 외부에 공유하지 마세요.

---

## 실행 방법

### 포그라운드 실행 (기본)

```bash
source .venv/bin/activate
python main.py
```

터미널을 닫거나 MacBook 덮개를 닫으면 프로세스가 종료됩니다.

### 백그라운드 실행 (MacBook 닫아도 유지)

MacBook을 닫은 뒤에도 프로그램이 계속 실행되려면, macOS의 `launchd` 데몬으로 등록해야 합니다.

#### 방법 1. launchd (권장 — macOS 네이티브, 재부팅 후에도 자동 시작)

**1) plist 파일 생성**

```bash
cat > ~/Library/LaunchAgents/com.kis.autotrader.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kis.autotrader</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python</string>
        <string>/Users/songhansu/IdeaProjects/kis-autotrader/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/logs/autotrader.out.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/logs/autotrader.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
```

**2) 로그 디렉토리 생성 및 서비스 등록**

```bash
mkdir -p ~/IdeaProjects/kis-autotrader/logs

# 서비스 등록 및 시작
launchctl load ~/Library/LaunchAgents/com.kis.autotrader.plist

# 상태 확인
launchctl list | grep kis
```

**3) 서비스 관리 명령어**

```bash
# 중지
launchctl unload ~/Library/LaunchAgents/com.kis.autotrader.plist

# 재시작 (중지 후 시작)
launchctl unload ~/Library/LaunchAgents/com.kis.autotrader.plist
launchctl load ~/Library/LaunchAgents/com.kis.autotrader.plist

# 로그 확인
tail -f ~/IdeaProjects/kis-autotrader/logs/autotrader.out.log
tail -f ~/IdeaProjects/kis-autotrader/logs/autotrader.err.log

# 완전 삭제
launchctl unload ~/Library/LaunchAgents/com.kis.autotrader.plist
rm ~/Library/LaunchAgents/com.kis.autotrader.plist
```

> `RunAtLoad`가 `true`이므로 macOS 로그인 시 자동으로 시작됩니다.
> `KeepAlive`가 `true`이므로 프로세스가 비정상 종료되면 자동으로 재시작됩니다.

#### 방법 2. nohup + caffeinate (간편 — 일회성 실행)

```bash
# caffeinate: MacBook 덮개를 닫아도 sleep 방지
# nohup: 터미널 종료 후에도 프로세스 유지
cd ~/IdeaProjects/kis-autotrader
caffeinate -s nohup .venv/bin/python main.py > logs/autotrader.out.log 2>&1 &

# 프로세스 ID 확인
echo $!

# 실행 확인
ps aux | grep main.py

# 종료
kill $(pgrep -f "python main.py")
```

> `caffeinate -s`는 시스템 sleep을 방지합니다.
> 단, MacBook을 재부팅하면 다시 실행해야 합니다. 지속적 운영에는 방법 1(launchd)을 권장합니다.

#### 방법 비교

| 항목 | launchd | nohup + caffeinate |
|------|---------|--------------------|
| MacBook 덮개 닫기 | 유지 | 유지 (caffeinate) |
| macOS 재부팅 후 | **자동 시작** | 수동 재실행 필요 |
| 비정상 종료 시 | **자동 재시작** (KeepAlive) | 종료됨 |
| 로그 관리 | plist에서 경로 지정 | 리다이렉션으로 관리 |
| 설정 난이도 | 중간 (plist 작성) | 쉬움 (한 줄) |

---

## 환경변수 설정

`.env` 파일에 아래 항목을 설정합니다.

```env
# KIS API (한국투자증권 OpenAPI)
KIS_APP_KEY=발급받은_앱키
KIS_APP_SECRET=발급받은_앱시크릿
KIS_ACCOUNT_NO=계좌번호
KIS_ACCOUNT_PRODUCT_CODE=01
KIS_ENV=virtual                    # virtual(모의투자) 또는 real(실전)

# Database
DATABASE_URL=postgresql://kis_user:kis_password@localhost:5432/kis_trader

# Google Calendar
GOOGLE_CALENDAR_ID=캘린더_ID
GOOGLE_CREDENTIALS_PATH=credentials.json

# Rate Limit
API_RATE_LIMIT_PER_SECOND=3        # 초당 API 호출 제한
API_DAILY_CALL_LIMIT=10000         # 일일 API 호출 상한
WS_MAX_RECONNECT_ATTEMPTS=5       # 웹소켓 최대 재연결 시도
WS_RECONNECT_BASE_DELAY=5         # 웹소켓 재연결 기본 대기(초)

# Trading
MAX_LOSS_RATE=0.03                 # 최대 손실률 (3%)
MAX_POSITION_RATIO=0.2             # 최대 포지션 비율 (20%)
DAILY_TRADE_LIMIT=10               # 일일 매매 횟수 제한
```

---

## 매매 전략

### 이동평균 교차 (Moving Average Crossover)

| 시그널 | 조건 | 기본 설정 |
|--------|------|-----------|
| 매수 (BUY) | 단기 MA가 장기 MA를 상향 돌파 (골든크로스) | 단기 5일, 장기 20일 |
| 매도 (SELL) | 단기 MA가 장기 MA를 하향 돌파 (데드크로스) | 단기 5일, 장기 20일 |
| 관망 (HOLD) | 교차 없음 | — |

### RSI (Relative Strength Index)

| 시그널 | 조건 | 기본 설정 |
|--------|------|-----------|
| 매수 (BUY) | RSI < 과매도 임계값 | RSI 기간 14일, 임계값 30 |
| 매도 (SELL) | RSI > 과매수 임계값 | RSI 기간 14일, 임계값 70 |
| 관망 (HOLD) | 30 ≤ RSI ≤ 70 | — |

### 전략 확장

`BaseStrategy`를 상속하여 새 전략을 추가할 수 있습니다:

```python
from src.strategy.base import BaseStrategy, Signal, SignalType
import pandas as pd

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "나만의 전략"

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        # 분석 로직 구현
        return Signal(signal_type=SignalType.HOLD, confidence=0.0)
```

## API 안전장치

### Rate Limiter (3중 제어)

1. **Token Bucket** — 초당 최대 호출 수 제한 (기본 3건/초)
2. **최소 호출 간격** — 연속 호출 시 334ms 이상 간격 보장
3. **일일 한도** — 일일 최대 API 호출 횟수 추적 (기본 10,000건)

### Circuit Breaker

연속 5회 실패 시 30초간 요청을 자동 차단하여 API 서버 부담을 방지합니다.

### 재시도 정책

| 응답 코드 | 동작 |
|-----------|------|
| 429 (Too Many Requests) | `Retry-After` 헤더만큼 대기 후 재시도 |
| 5xx (Server Error) | Exponential backoff (1초 → 2초 → 4초, 최대 3회) |
| 4xx (Client Error) | 즉시 예외 발생 |

### 웹소켓 상태 머신

```
DISCONNECTED → CONNECTING → CONNECTED → SUBSCRIBING → ACTIVE
     ↑                                                    │
     └────────────── 재연결 (exponential backoff) ─────────┘
```

- 재연결 대기: 5초 → 10초 → 20초 → 40초 → 60초 (최대)
- 최대 재연결 시도: 5회, 초과 시 중단
- 구독 디바운싱: 최소 1초 간격

## 스케줄러

| 시간 | 작업 | 설명 |
|------|------|------|
| 08:30 | `pre_market_job` | OAuth 토큰 갱신, 관심종목 로딩 |
| 09:00~15:20 | `trading_job` | 시세 조회 → 전략 실행 → 주문 (종목 수 기반 간격 자동 계산) |
| 15:40 | `post_market_job` | 일일 결산, DailyPerformance 저장, Calendar 이벤트 등록 |

장중 시세 조회 간격은 종목 수에 따라 API 호출 제한(초당 3건)을 준수하도록 자동 계산됩니다.

## DB 스키마

```
┌──────────┐     ┌──────────┐     ┌────────────┐
│  Stock   │←────│  Order   │←────│ Execution  │
│──────────│     │──────────│     │────────────│
│ code(UK) │     │ type     │     │ exec_price │
│ name     │     │ quantity │     │ exec_qty   │
│ market   │     │ price    │     │ exec_at    │
└────┬─────┘     │ status   │     └────────────┘
     │           └──────────┘
     │
     ↓
┌──────────┐     ┌───────────────────┐
│Portfolio │     │ DailyPerformance  │
│──────────│     │───────────────────│
│ quantity │     │ date (UK)         │
│ avg_price│     │ total_profit_loss │
│ cur_price│     │ profit_rate       │
└──────────┘     │ execution_count   │
                 │ details (JSON)    │
                 └───────────────────┘
```

## Google Calendar 이벤트

장 마감 후 자동 생성되는 캘린더 이벤트 예시:

- **제목**: `[매매결과] 2026-03-31 +2.5% (3건 체결)`
- **시간**: 15:30~16:00 (KST)
- **본문**: 일일 손익 요약 + 종목별 매수/매도/손익 상세 내역

## 개발

### 테스트

```bash
# 전체 테스트
pytest tests/ -v

# 모듈별 테스트
pytest tests/test_api/ -v
pytest tests/test_strategy/ -v
pytest tests/test_db/ -v
pytest tests/test_calendar/ -v
```

### 코드 품질

```bash
# 린트
ruff check src/

# 타입 체크
mypy src/
```

### DB 마이그레이션

```bash
# 모델 변경 후 마이그레이션 생성
alembic revision --autogenerate -m "설명"

# 마이그레이션 적용
alembic upgrade head

# 롤백
alembic downgrade -1
```

## 주의사항

- KIS OpenAPI 신규 신청 후 3일간 **초당 3건** 호출 제한이 적용됩니다.
- 모의투자(`KIS_ENV=virtual`)에서 충분히 테스트 후 실전 전환하세요.
- `credentials.json`, `token.json`, `.env` 파일은 절대 git에 커밋하지 마세요.
- 웹소켓 연결/종료를 무한 반복하면 IP 및 앱키가 차단될 수 있습니다.

## 라이선스

Private — 비공개 프로젝트
