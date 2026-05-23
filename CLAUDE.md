# KIS 주식 자동매매 시스템

## 프로젝트 개요

한국투자증권(KIS) OpenAPI를 활용한 주식 자동매매 시스템.
장중 자동 시세 조회, 전략 기반 매매, 리스크 관리, 일일 결과 Google Calendar 등록,
Telegram 알림/원격 명령, Streamlit 대시보드까지 통합 운영한다.

## 기술 스택

- **Language**: Python 3.12+
- **HTTP Client**: httpx (async)
- **WebSocket**: websockets
- **Database**: PostgreSQL + SQLAlchemy 2.0 + Alembic
- **Data Analysis**: pandas
- **Validation**: pydantic 2.5+
- **Scheduler**: APScheduler
- **API**: KIS OpenAPI (한국투자증권)
- **Calendar**: Google Calendar API (google-api-python-client + google-auth-oauthlib)
- **Notification**: Telegram Bot API (httpx)
- **Dashboard**: Streamlit
- **Test**: pytest + pytest-asyncio + pytest-cov + respx (httpx mock)
- **Lint/Type**: ruff, mypy (strict mode)
- **Infra**: Docker + docker-compose, launchd (macOS)

## 디렉토리 구조

```
kis-autotrader/
├── CLAUDE.md
├── README.md
├── .env.example
├── pyproject.toml
├── alembic.ini
├── config_overrides.json          # 런타임 설정 오버라이드 (선택)
├── Dockerfile
├── docker-compose.yml
├── alembic/
│   └── versions/                  # 마이그레이션 스크립트
├── src/
│   ├── __init__.py
│   ├── config.py                  # 환경변수, 설정값 통합 관리 (Settings 객체)
│   ├── engine.py                  # 매매 엔진: 시세→전략→리스크→주문→DB
│   ├── api/
│   │   ├── auth.py                # OAuth 인증, 토큰 발급/갱신
│   │   ├── client.py              # HTTP 클라이언트 (재시도, Circuit Breaker)
│   │   ├── rate_limiter.py        # 호출 제한 관리 (Token Bucket)
│   │   ├── order.py               # 주문 API (매수/매도/정정/취소)
│   │   ├── quote.py               # 시세 조회 API (현재가, 일봉, 분봉, 거래량순위)
│   │   ├── account.py             # 잔고/체결내역 조회
│   │   ├── websocket.py           # 실시간 웹소켓 매니저
│   │   └── health.py              # 헬스체크 HTTP 서버 (/health)
│   ├── strategy/
│   │   ├── base.py                # 매매 전략 추상 클래스 + Signal
│   │   ├── moving_average.py      # 이동평균 교차 전략
│   │   ├── rsi.py                 # RSI 기반 전략
│   │   ├── macd.py                # MACD 전략 (EMA 교차)
│   │   ├── bollinger.py           # 볼린저밴드 전략 (%B 지표)
│   │   ├── ensemble.py            # 앙상블 (다중 전략 투표)
│   │   ├── registry.py            # 전략 레지스트리
│   │   ├── selector.py            # 종목별 전략 셀렉터
│   │   ├── screener.py            # 종목 스크리닝 (필터+스코어링)
│   │   └── risk.py                # 리스크 관리 (손절/익절/MDD/연패)
│   ├── backtest/
│   │   ├── engine.py              # 백테스트 시뮬레이션 엔진
│   │   ├── broker.py              # 가상 브로커 (주문 실행/잔고 관리)
│   │   ├── data_loader.py         # 과거 데이터 로더
│   │   └── report.py              # 백테스트 결과 리포트
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM 모델
│   │   ├── session.py             # DB 세션 관리
│   │   ├── repository.py          # CRUD Repository
│   │   ├── analytics.py           # 매매 분석 쿼리 (MDD, Sharpe 등)
│   │   └── event_logger.py        # 구조화 이벤트 로깅
│   ├── scheduler/
│   │   ├── jobs.py                # APScheduler 작업 정의
│   │   └── holidays.py            # 공휴일/휴장일 판단 (holidays.json)
│   ├── calendar/
│   │   ├── google_auth.py         # Google OAuth2 인증
│   │   └── event.py               # 캘린더 이벤트 생성
│   ├── notify/
│   │   ├── telegram.py            # Telegram Bot API 전송
│   │   ├── formatter.py           # 알림 메시지 포맷팅 (매수/매도/결산/에러/시스템)
│   │   └── bot.py                 # Telegram 봇 명령 수신
│   └── utils/
│       ├── logger.py              # 로깅 설정 (일자별+크기별 로테이션)
│       └── exceptions.py          # 커스텀 예외 클래스 (13종)
├── scripts/
│   ├── watchdog.sh                # 프로세스 감시 + 자동 재시작 (주말/공휴일 인식)
│   ├── run_auto_implement.sh      # Claude Code 자동 구현 스크립트
│   ├── run_backtest.py            # 백테스트 실행
│   ├── run_dashboard.sh           # 대시보드 실행
│   ├── query_analytics.py         # 매매 분석 쿼리 실행
│   ├── generate_daily_report.py   # 일일 리포트 생성
│   ├── backup_db.sh               # DB 백업 (pg_dump + gzip, 7일 롤링)
│   └── docker-entrypoint.sh       # Docker 엔트리포인트
├── dashboard/                     # Streamlit 웹 대시보드
│   ├── app.py                     # 메인 대시보드
│   └── pages/
│       ├── trades.py              # 매매 분석
│       ├── performance.py         # 성과 분석
│       ├── signals.py             # 시그널 분석
│       └── risk.py                # 리스크 분석 (MDD, Sharpe, 연패)
├── docs/
│   ├── BRIDGE_SPEC.md             # Cowork ↔ Claude Code 브릿지 규격
│   ├── CHANGELOG.md               # 자동 구현 변경 이력 (최근 5건 rolling, 전체는 DB)
│   ├── proposals/                 # Cowork가 작성하는 개선 제안서
│   └── reports/                   # 일일/주간 매매 리포트
├── tests/
│   ├── test_api/
│   ├── test_strategy/
│   ├── test_backtest/
│   ├── test_notify/
│   ├── test_db/
│   ├── test_scheduler/
│   ├── test_calendar/
│   ├── test_analytics.py
│   ├── test_config.py
│   └── test_engine_db_integration.py
└── main.py                        # 엔트리포인트
```

## 코딩 컨벤션

- `from __future__ import annotations` 모든 소스 파일 첫줄에 사용
- Type hints 필수 (모든 함수 시그니처에 적용)
- docstring은 한글로 작성
- 클래스/함수명은 영어, 주석/문서는 한글
- 상수는 대문자 스네이크 케이스 (`MAX_RETRY_COUNT`)
- 설정 클래스는 `@dataclass(frozen=True)` 패턴 사용
- ruff 규칙: `["E", "F", "I", "N", "W", "UP"]`, line-length=100
- mypy: strict mode 활성화

### 환경변수 네이밍 규칙

| Prefix | 영역 | 예시 |
|--------|------|------|
| `KIS_` | KIS API 인증/환경 | `KIS_APP_KEY`, `KIS_ENV` |
| `API_` | API 호출 제한 | `API_RATE_LIMIT_PER_SECOND`, `API_DAILY_CALL_LIMIT` |
| `WS_` | 웹소켓 | `WS_MAX_RECONNECT_ATTEMPTS` |
| `MAX_` | 매매 리스크 한도 | `MAX_LOSS_RATE`, `MAX_POSITION_RATIO` |
| `STRATEGY_` | 전략 파라미터 | `STRATEGY_DEFAULT`, `STRATEGY_MA_SHORT_PERIOD` |
| `SCREENING_` | 스크리닝 설정 | `SCREENING_TOP_N`, `SCREENING_MIN_PRICE` |
| `TELEGRAM_` | 알림 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ENABLED` |
| `GOOGLE_` | 캘린더 | `GOOGLE_CALENDAR_ID` |
| `DATABASE_` | DB 접속 | `DATABASE_URL` |
| `HEALTH_` | 헬스체크 | `HEALTH_PORT` |

### 커스텀 예외 클래스 (`src/utils/exceptions.py`)

| 예외 | 용도 |
|------|------|
| `KISAutoTraderError` | 최상위 예외 (모든 커스텀 예외의 부모) |
| `AuthenticationError` | OAuth 인증 실패 |
| `TokenExpiredError` | 토큰 만료 |
| `RateLimitExceededError` | API 호출 제한 초과 |
| `DailyLimitExceededError` | 일일 API 한도 초과 |
| `OrderError` | 주문 실패 |
| `InsufficientBalanceError` | 잔고 부족 |
| `WebSocketError` | 웹소켓 에러 |
| `WebSocketReconnectFailedError` | 웹소켓 재연결 실패 |
| `StrategyError` | 전략 실행 에러 |
| `RiskLimitError` | 리스크 한도 초과 |
| `DatabaseError` | DB 작업 에러 |
| `CalendarError` | Google Calendar 에러 |

### 로깅 규약 (`src/utils/logger.py`)

- **모듈별 로거**: `logger = setup_logger(__name__)` — 모든 모듈에서 동일 패턴 사용
- **로그 포맷**: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- **파일 핸들러**:
  - `logs/autotrader.log` — INFO 이상, 일자별 로테이션 (30일 보관)
  - `logs/autotrader.size.log` — WARNING 이상, 크기별 로테이션 (50MB × 5개)
- **콘솔 핸들러**: WARNING 이상만 stdout 출력 (launchd stdout 캡처용)
- 매매/주문은 `log_trade()`, 경고는 `log_warning()` (이벤트 DB에도 기록)

## 검증 명령어

```bash
pytest tests/                    # 전체 테스트
pytest tests/test_api/ -v        # API 모듈 테스트
pytest tests/test_strategy/ -v   # 전략 모듈 테스트
pytest tests/test_backtest/ -v   # 백테스트 테스트
pytest tests/test_notify/ -v     # 알림 모듈 테스트
python -m mypy src/              # 타입 체크 (strict)
ruff check src/                  # 린트
ruff check src/ --fix            # 린트 자동 수정
```

### 테스트 조직 규칙

- **단위 테스트**: `tests/test_{모듈명}/` 디렉토리 아래 배치
- **통합 테스트**: `tests/test_engine_db_integration.py` 등 파일명에 명시
- **외부 API mock 규칙**: KIS API, Telegram API 등 외부 호출은 반드시 mock 처리
- **Fixture 위치**: 공통 fixture는 `tests/conftest.py`, 모듈별은 해당 디렉토리의 `conftest.py`
- **DB 테스트**: SQLite in-memory 또는 테스트 전용 PostgreSQL 사용, 프로덕션 DB 직접 접근 금지

### Alembic 마이그레이션 워크플로우

```bash
# 1. src/db/models.py에서 모델 수정/추가
# 2. 마이그레이션 스크립트 자동 생성
alembic revision --autogenerate -m "설명"

# 3. 생성된 스크립트 검토 (alembic/versions/)
# 4. 마이그레이션 적용
alembic upgrade head

# 5. 롤백 (필요 시)
alembic downgrade -1
```

## 설정 시스템 (`src/config.py`)

모든 설정은 `Settings` 통합 객체에서 관리한다. 설정 우선순위:

1. `config_overrides.json` — 자동 파이프라인이 파라미터 튜닝 시 사용 (BRIDGE_SPEC 범위 내)
2. `.env` — 개발자가 로컬 환경을 설정할 때 사용 (인증 정보, DB URL 등)
3. 코드 기본값 — `src/config.py`에 정의된 fallback 값

> **역할 분리**: `.env`는 환경별 인증 정보/인프라 설정, `config_overrides.json`은 전략 파라미터 튜닝 전용.

`config_overrides.json` 형식:
```json
{
  "_meta": { "updated_at": "2026-04-14", "updated_by": "cowork" },
  "SCREENING_TOP_N": 30,
  "STRATEGY_MIN_CONFIDENCE": 0.15
}
```

### 환경별 기본값 차이

| 설정 | 모의투자 (virtual) | 실전 (real) |
|------|---------------------|-------------|
| API 초당 호출 | 5회 | 20회 |
| API 일일 한도 | 50,000회 | 50,000회 |
| DB URL | `DATABASE_URL` | `DATABASE_URL_REAL` → `DATABASE_URL` 폴백 |

## 모듈 경계 (담당 영역)

| 디렉토리 | 담당 에이전트 | 비고 |
|-----------|---------------|------|
| src/api/ | api-engineer | KIS API 통신 전담. RateLimiter 여기서 구현 |
| src/strategy/, src/backtest/ | strategy-engineer | API 직접 호출 금지. 데이터를 인자로 받음 |
| src/db/, src/scheduler/ | db-scheduler-engineer | 데이터 영속성 + 스케줄링 |
| src/calendar/ | calendar-engineer | Google Calendar 연동 전담 |
| src/config.py, src/utils/ | team lead | 공통 설정/유틸리티 |
| src/engine.py | team lead | 매매 파이프라인 통합 (시세→전략→리스크→주문→DB) |
| src/notify/ | team lead | Telegram 알림 전송 + Bot 명령 |
| dashboard/ | team lead | Streamlit 웹 대시보드 |
| main.py | team lead | 최종 조합 및 엔트리포인트 |

> **모듈 경계 규칙**: 담당 에이전트 호출을 우선하되, 단순 수정(오타, import 추가 등)은 직접 가능.
> 인터페이스 변경이나 로직 변경 시에는 담당 에이전트와 합의할 것.

### 모듈 의존성 방향 (반드시 준수)

```
main.py → engine.py → api/, strategy/, db/, calendar/, notify/
strategy/ → (데이터를 인자로 받음, api/ 직접 호출 금지)
scheduler/jobs.py → engine.py
```

---

## ⚠️ KIS API 호출 제한 정책

### 1. REST API 초당 호출 제한

- **모의투자**: 기본 **초당 5건** (`API_RATE_LIMIT_PER_SECOND=5`)
- **실전투자**: 기본 **초당 20건** (`API_RATE_LIMIT_PER_SECOND=20`)
- **신규 고객**: 신청 후 3일간 초당 3건 제한 → 이후 기본 유량 상향

구현 사항 (`src/api/rate_limiter.py`):
- Token Bucket 방식 Rate Limiter 구현
- 초당 최대 호출 수를 **설정값으로 관리** (KIS_ENV에 따라 자동 결정)
- 모든 REST API 호출은 반드시 이 Rate Limiter를 경유해야 함
- 호출 대기열(queue) 구현하여 제한 초과 시 자동 대기

### 2. 웹소켓 연결 제한 (IP/앱키 차단 위험)

무한 연결/종료 반복 시 **IP 및 앱키가 일시 차단**됨.

**정상 패턴** (반드시 이 순서를 따를 것):
```
연결 → 종목 구독 → 데이터 수신 → 구독 해제 → 연결 종료
```

**금지 패턴** (구현 시 절대 발생하지 않도록 할 것):
- 웹소켓 연결 직후 바로 종료 반복
- 데이터 수신 확인 없이 구독 등록/해제 무한 반복

구현 사항:
- 재연결 시 **exponential backoff** 적용 (5초 → 10초 → 20초 → 최대 60초)
- 최대 재연결 시도 횟수 제한 (기본 5회, 이후 알림 후 중단)
- 종목 구독 후 **수신 확인(heartbeat/첫 데이터)** 확인 후 다음 동작
- 구독 등록/해제에 **디바운싱** 적용 (최소 1초 간격)
- 연결 상태 머신: DISCONNECTED → CONNECTING → CONNECTED → SUBSCRIBING → ACTIVE

### 3. Circuit Breaker

- 연속 5회 실패 시 서킷 열림 → 요청 자동 차단
- 반복 트립 시 대기 시간 점진 증가: 30초 → 60초 → 120초 → 240초 → 300초(최대)
- 성공 시 트립 카운트 + 백오프 전부 초기화
- 서킷 브레이커 열림 시 매매 사이클도 즉시 중단 (스케줄러 블로킹 방지)

### 4. 공통 안전장치

- API 에러 응답 처리:
  - `429 Too Many Requests` → Rate Limit 대기 후 재시도
  - `5xx` → exponential backoff 재시도 (최대 3회)
  - 그 외 에러 → 로그 기록 후 예외 발생
- 일일 최대 API 호출 횟수 상한 설정 (기본 50,000회)
- 모든 API 호출/응답을 로그에 기록 (호출 시각, 엔드포인트, 응답코드)

### 5. 스케줄러 호출 시 주의

- 시세 조회 주기를 초당 호출 제한 이하로 설정
- 종목 수 × 조회 빈도 계산 필수 (`_calculate_trading_interval()` 자동 산출)
- `src/api/rate_limiter.py`의 RateLimiter를 **반드시** 사용할 것
- 스케줄러 중복 실행 방지 (`misfire_grace_time`, `max_instances=1` 설정)

---

## Google Calendar 연동 가이드

- `google-api-python-client` + `google-auth-oauthlib` 사용
- OAuth2 credentials는 `credentials.json`으로 관리 (gitignore 필수)
- 이벤트 형식:
  - **제목**: `[매매결과] 2026-03-31 +2.5% (3건 체결)`
  - **시간**: 당일 장 마감 시간 (15:30) 기준 30분 이벤트
  - **설명**: 종목별 매수/매도 내역, 수익률, 총 손익 요약 (마크다운 형식)
  - **캘린더**: 사용자 지정 캘린더 ID (config.py에서 관리)

---

## 환경변수 (.env)

> 전체 목록은 `.env.example` 참조. 아래는 주요 환경변수와 기본값.

```env
# KIS API
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_number
KIS_ACCOUNT_PRODUCT_CODE=01
KIS_ENV=virtual                    # virtual(모의) 또는 real(실전)

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/kis_trader
# DATABASE_URL_REAL=...            # 실전 환경 전용 DB (선택)

# Google Calendar
GOOGLE_CALENDAR_ID=your_calendar_id
GOOGLE_CREDENTIALS_PATH=credentials.json

# Rate Limit (KIS_ENV에 따라 자동 결정되므로 생략 가능)
# API_RATE_LIMIT_PER_SECOND=5     # virtual=5, real=20
# API_DAILY_CALL_LIMIT=50000
# WS_MAX_RECONNECT_ATTEMPTS=5
# WS_RECONNECT_BASE_DELAY=5

# Trading
MAX_LOSS_RATE=0.03
MAX_POSITION_RATIO=0.2
DAILY_TRADE_LIMIT=10
MAX_DAILY_TRADES_PER_STOCK=2       # 종목별 당일 최대 진입(매수) 횟수 (동일 종목 다중 진입 차단)
# MAX_DAILY_DRAWDOWN=0.05
# MAX_CONSECUTIVE_LOSSES=5

# Strategy (생략 시 기본값 사용)
# STRATEGY_DEFAULT=ensemble
# STRATEGY_ENSEMBLE_METHOD=weighted
# STRATEGY_MIN_CONFIDENCE=0.1

# Screening (생략 시 기본값 사용)
# SCREENING_TOP_N=20
# SCREENING_INTERVAL_CYCLES=60
# MAX_SCREENED_STOCKS=15

# Telegram
# TELEGRAM_BOT_TOKEN=your_bot_token
# TELEGRAM_CHAT_ID=your_chat_id
# TELEGRAM_ENABLED=false

# Docker PostgreSQL (docker-compose 전용)
POSTGRES_DB=kis_trader
POSTGRES_USER=kis
POSTGRES_PASSWORD=change_me_to_strong_password

# Health Check
# HEALTH_PORT=18923
# HEALTH_ENABLED=true
```

---

## 실행 방법

### 로컬 실행 (포그라운드)

```bash
source .venv/bin/activate
python main.py
```

### Docker 실행

```bash
docker-compose up -d               # PostgreSQL + autotrader 실행
docker-compose logs -f autotrader   # 로그 확인
docker-compose down                 # 중지
```

### macOS launchd (백그라운드, 재부팅 후 자동 시작)

```bash
# 서비스 시작/중지/재시작
launchctl start com.kis.autotrader
launchctl stop com.kis.autotrader
launchctl stop com.kis.autotrader && sleep 2 && launchctl start com.kis.autotrader
```

### 대시보드 실행

```bash
.venv/bin/streamlit run dashboard/app.py --server.port 8501
# 또는
scripts/run_dashboard.sh
```

---

## 문서 필수 업데이트 규칙

소스 코드를 수정할 때 아래 문서를 반드시 함께 업데이트할 것:

### 1. 구현 이력 기록 (필수)
- **모든 코드 변경 시** `scripts/record_implementation.py`를 실행하여 DB에 기록한다.
- `docs/CHANGELOG.md`는 **최근 5건 rolling summary**만 유지 — 새 항목 추가 시 가장 오래된 항목 제거.
- 커밋 전에 반드시 DB 기록 + CHANGELOG rolling 갱신 완료할 것.

### 2. `README.md` (해당 시 업데이트)
아래 항목에 해당하는 변경이 있으면 README.md도 함께 업데이트한다:
- 새로운 기능/모듈 추가 (주요 기능 목록, 프로젝트 구조)
- 전략 추가/변경 (매매 전략 섹션)
- DB 모델 추가/변경 (DB 스키마 섹션)
- API 안전장치 동작 변경 (Circuit Breaker, Rate Limiter 등)
- Telegram Bot 명령어 추가/변경
- 환경변수 추가/변경
- 테스트 카운트가 크게 변동된 경우

### 3. `CLAUDE.md` (해당 시 업데이트)
- 디렉토리 구조 변경 시
- 코딩 컨벤션 변경 시
- 모듈 경계/담당 변경 시
- API 호출 제한 정책 변경 시

---

## Cowork ↔ Claude Code 완전 자동 파이프라인

Cowork(분석/기획)와 Claude Code(구현)가 `docs/` 디렉토리를 브릿지로 소통합니다.
**사람의 승인 없이 자동으로 동작하며, 안전 게이트가 검증을 대신합니다.**

- **규격 문서**: `docs/BRIDGE_SPEC.md` (반드시 먼저 읽을 것 — 안전 게이트 규칙 포함)
- **제안서**: `docs/proposals/*.md` — Cowork가 `ready` 상태로 작성
- **리포트**: `docs/reports/*.md` — 일일/주간 성과 분석
- **변경 이력**: `implementation_logs` DB 테이블 + `docs/CHANGELOG.md` (최근 5건 rolling)

### Claude Code 자동 구현 흐름

1. `docs/BRIDGE_SPEC.md`를 읽어 안전 게이트 규칙을 로드
2. `docs/proposals/`에서 `상태: ready` 인 제안서를 날짜순으로 수집
3. 각 제안서에 대해 안전 게이트 검증 (금지 영역, 파라미터 범위, 코드 변경 규칙)
4. 통과 시 → 변경 스펙에 따라 코드 수정 → pytest + mypy + ruff 검증
5. 전부 pass → `implemented` 처리, DB `implementation_logs`에 기록 + `docs/CHANGELOG.md` rolling 갱신
6. 하나라도 fail → `git restore`로 원복, `failed` 처리
7. 구현된 것이 있으면 서비스 재시작

> **파라미터 변경 범위**: BRIDGE_SPEC에서 기본값 ±50% 범위 내 자율 변경 허용.
> 범위 초과 또는 고위험 변경(손절률, 최대 포지션 등)은 사용자 확인 게이트를 거친다.
