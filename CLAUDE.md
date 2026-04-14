# KIS 주식 자동매매 시스템

## 프로젝트 개요

한국투자증권(KIS) OpenAPI를 활용한 주식 자동매매 시스템.
당일 매매 결과를 Google Calendar에 자동 등록하고, Telegram으로 알림을 전송한다.

## 기술 스택

- **Language**: Python 3.12+
- **HTTP Client**: httpx
- **WebSocket**: websockets
- **Database**: PostgreSQL + SQLAlchemy 2.0 + Alembic
- **Data**: pandas
- **Validation**: pydantic 2.5+
- **Scheduler**: APScheduler
- **API**: KIS OpenAPI (한국투자증권)
- **Calendar**: Google Calendar API (google-api-python-client + google-auth-oauthlib)
- **Notification**: Telegram Bot API
- **Test**: pytest + pytest-asyncio + pytest-cov + respx (httpx mock)
- **Lint/Type**: ruff, mypy (strict mode)
- **Infra**: Docker + docker-compose, launchd (macOS)

## 디렉토리 구조

```
kis-autotrader/
├── CLAUDE.md
├── .env.example
├── pyproject.toml
├── alembic.ini
├── config_overrides.json       # 런타임 설정 오버라이드 (선택)
├── docker-compose.yml          # PostgreSQL + 앱 + 대시보드
├── Dockerfile                  # 메인 앱 컨테이너
├── Dockerfile.dashboard        # Streamlit 대시보드 컨테이너
├── alembic/
│   └── versions/               # DB 마이그레이션 파일
├── src/
│   ├── __init__.py
│   ├── config.py               # 환경변수, 설정값 관리 (Settings 통합 객체)
│   ├── engine.py               # 핵심 매매 엔진 (시세→전략→리스크→주문→DB 파이프라인)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py             # OAuth 인증, 토큰 발급/갱신
│   │   ├── client.py           # KIS API 기본 클라이언트
│   │   ├── rate_limiter.py     # 호출 제한 관리 (Token Bucket)
│   │   ├── order.py            # 주문 API (매수/매도/정정/취소)
│   │   ├── quote.py            # 시세 조회 API
│   │   ├── account.py          # 잔고/계좌 조회 API
│   │   ├── websocket.py        # 실시간 웹소켓 매니저
│   │   └── health.py           # 헬스체크 HTTP 서버
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py             # 매매 전략 추상 클래스
│   │   ├── moving_average.py   # 이동평균 교차 전략
│   │   ├── rsi.py              # RSI 기반 전략
│   │   ├── ensemble.py         # 앙상블 (다중 전략 투표)
│   │   ├── registry.py         # 전략 레지스트리
│   │   ├── selector.py         # 종목별 전략 셀렉터
│   │   ├── macd.py             # MACD 전략
│   │   ├── bollinger.py        # 볼린저밴드 전략
│   │   ├── risk.py             # 리스크 관리 모듈
│   │   └── screener.py         # 종목 스크리닝 (필터+스코어링)
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py           # 백테스트 엔진
│   │   ├── broker.py           # 가상 브로커 (주문 시뮬레이션)
│   │   ├── data_loader.py      # 과거 데이터 로딩
│   │   └── report.py           # 백테스트 결과 리포트
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy 모델
│   │   ├── session.py          # DB 세션 관리
│   │   ├── repository.py       # 데이터 접근 레이어
│   │   ├── analytics.py        # 매매 분석 쿼리
│   │   └── event_logger.py     # 구조화 이벤트 로깅
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── jobs.py             # APScheduler 작업 정의
│   │   └── holidays.py         # 공휴일/휴장일 판단
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── google_auth.py      # Google OAuth2 인증
│   │   └── event.py            # 캘린더 이벤트 생성
│   ├── notify/
│   │   ├── __init__.py
│   │   ├── telegram.py         # Telegram 알림 전송
│   │   ├── formatter.py        # 메시지 포매터 (매수/매도/일일요약/시스템)
│   │   └── bot.py              # Telegram 봇 명령 수신
│   └── utils/
│       ├── __init__.py
│       ├── exceptions.py       # 커스텀 예외 계층 (KISAutoTraderError 기반)
│       └── logger.py           # 로깅 설정
├── scripts/
│   ├── watchdog.sh             # 프로세스 행 감지 + 자동 재시작 (주말/공휴일 인식)
│   ├── run_auto_implement.sh   # Claude Code 자동 구현 스크립트
│   ├── run_backtest.py         # 백테스트 실행
│   ├── run_dashboard.sh        # Streamlit 대시보드 실행
│   ├── generate_daily_report.py # 일일 리포트 생성
│   ├── query_analytics.py      # 매매 분석 쿼리 실행
│   ├── backup_db.sh            # DB 백업
│   └── docker-entrypoint.sh    # Docker 엔트리포인트
├── dashboard/                   # Streamlit 웹 대시보드
│   ├── app.py                   # 메인 대시보드
│   └── pages/
│       ├── trades.py            # 매매 분석
│       ├── performance.py       # 성과 분석
│       ├── signals.py           # 시그널 분석
│       └── risk.py              # 리스크 분석 (MDD, Sharpe, 연패)
├── tests/
│   ├── test_api/
│   ├── test_strategy/
│   ├── test_db/
│   ├── test_calendar/
│   ├── test_notify/
│   ├── test_backtest/
│   ├── test_scheduler/
│   ├── test_analytics.py
│   ├── test_config.py
│   └── test_engine_db_integration.py
├── docs/
│   ├── BRIDGE_SPEC.md           # Cowork ↔ Claude Code 안전 게이트 규격
│   ├── CHANGELOG.md             # 변경 이력
│   ├── proposals/               # Cowork 제안서 (상태: ready/implemented/failed)
│   └── reports/                 # 일일/주간 성과 분석 리포트
└── main.py                      # 엔트리포인트
```

## 코딩 컨벤션

- `from __future__ import annotations` 모든 소스 파일 첫줄에 사용
- Type hints 필수 (모든 함수 시그니처에 적용)
- docstring은 한글로 작성
- 환경변수는 `.env` + `config_overrides.json`으로 관리
- 클래스/함수명은 영어, 주석/문서는 한글
- 상수는 대문자 스네이크 케이스 (`MAX_RETRY_COUNT`)
- 에러는 커스텀 예외 클래스로 정의 (`src/utils/exceptions.py`)
- 설정 클래스는 `@dataclass(frozen=True)` 패턴 사용
- 로깅: `setup_logger(__name__)` 또는 `logging.getLogger(__name__)` 사용
- ruff 규칙: `["E", "F", "I", "N", "W", "UP"]`, line-length=100
- mypy: strict mode 활성화

## 검증 명령어

```bash
pytest tests/                    # 전체 테스트
pytest tests/test_api/ -v        # API 모듈 테스트
python -m mypy src/              # 타입 체크 (strict)
ruff check src/                  # 린트
ruff check src/ --fix            # 린트 자동 수정
```

## 설정 시스템 (`src/config.py`)

모든 설정은 `Settings` 통합 객체에서 관리한다. 설정 우선순위:

1. `config_overrides.json` (최우선 — 재시작 없이 파라미터 변경 가능)
2. `.env` 파일 / 환경변수
3. 코드 내 기본값

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

## 모듈 경계 (Cowork 에이전트 팀 구조)

> 이 테이블은 Cowork 자동 파이프라인에서 에이전트 팀이 동작할 때의 담당 영역이다.
> 단독 작업 시에는 참고용이며, 모듈 간 의존성 방향만 준수하면 된다.

| 디렉토리 | 담당 에이전트 | 비고 |
|-----------|---------------|------|
| src/api/ | api-engineer | KIS API 통신 전담. RateLimiter 여기서 구현 |
| src/strategy/ | strategy-engineer | API 직접 호출 금지. 데이터를 인자로 받음 |
| src/backtest/ | strategy-engineer | 전략 검증용 백테스트 |
| src/db/, src/scheduler/ | db-scheduler-engineer | 데이터 영속성 + 스케줄링 |
| src/calendar/ | calendar-engineer | Google Calendar 연동 전담 |
| src/engine.py | team lead | 핵심 매매 파이프라인 오케스트레이션 |
| src/config.py, src/utils/ | team lead | 공통 설정/유틸리티 |
| src/notify/ | team lead | Telegram 알림/봇 |
| main.py | team lead | 최종 조합 및 엔트리포인트 |

### 모듈 의존성 방향 (반드시 준수)

```
main.py → engine.py → api/, strategy/, db/, calendar/, notify/
strategy/ → (데이터를 인자로 받음, api/ 직접 호출 금지)
scheduler/jobs.py → engine.py
```

---

## ⚠️ KIS API 호출 제한 정책

### 1. REST API 초당 호출 제한

- **신규 고객**: 신청 후 3일간 **초당 3건** 제한 → 이후 기본 유량 상향
- **모의투자 계좌**: 해당 없음 (기본 유량 유지)
- **서비스 해지 후 재등록 시 신규로 간주됨**

구현 사항 (`src/api/rate_limiter.py`):
- Token Bucket 방식 Rate Limiter 구현 완료
- 초당 최대 호출 수는 환경별 기본값 적용 (virtual=5, real=20, `.env`로 오버라이드 가능)
- 모든 REST API 호출은 반드시 이 Rate Limiter를 경유
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

### 3. 공통 안전장치

- API 에러 응답 처리:
  - `429 Too Many Requests` → Rate Limit 대기 후 재시도
  - `5xx` → exponential backoff 재시도 (최대 3회)
  - 그 외 에러 → 로그 기록 후 예외 발생
- 일일 최대 API 호출 횟수 상한 설정 (기본 50,000회)
- 모든 API 호출/응답을 로그에 기록 (호출 시각, 엔드포인트, 응답코드)
- 비정상 호출 패턴 감지 시 자동 중단 (circuit breaker)

### 4. 스케줄러 호출 시 주의

- 시세 조회 주기를 설정된 Rate Limit 이하로 유지
- 종목 수 × 조회 빈도 계산 필수
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
KIS_ENV=virtual                      # virtual(모의) 또는 real(실전)

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/kis_trader
# DATABASE_URL_REAL=...              # 실전 환경 전용 DB (선택)

# Google Calendar
GOOGLE_CALENDAR_ID=your_calendar_id
GOOGLE_CREDENTIALS_PATH=credentials.json

# Rate Limit (환경별 기본값: virtual=5, real=20)
# API_RATE_LIMIT_PER_SECOND=5
# API_DAILY_CALL_LIMIT=50000
WS_MAX_RECONNECT_ATTEMPTS=5
WS_RECONNECT_BASE_DELAY=5

# Trading
MAX_LOSS_RATE=0.03
MAX_POSITION_RATIO=0.2
DAILY_TRADE_LIMIT=10
# MAX_DAILY_DRAWDOWN=0.05
# MAX_CONSECUTIVE_LOSSES=5
# MARKET_CLOSE_CUTOFF_HOUR=14
# MARKET_CLOSE_CUTOFF_MINUTE=30

# Strategy
# STRATEGY_DEFAULT=ensemble
# STRATEGY_MAPPINGS=005930:rsi,000660:moving_average
# STRATEGY_ENSEMBLE_METHOD=weighted
# STRATEGY_MIN_CONFIDENCE=0.1
# TAKE_PROFIT_RATIO=0.05

# Screening (종목 스크리닝)
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
# HEALTH_PORT=8080
# HEALTH_ENABLED=true
```

---

## 문서 필수 업데이트 규칙

소스 코드를 수정할 때 아래 문서를 반드시 함께 업데이트할 것:

### 1. `docs/CHANGELOG.md` (필수)
- **모든 코드 변경 시** 변경 이력을 기록한다.
- 형식: `## [날짜] 제목` + 카테고리, 배경, 변경 파일, 검증 결과
- 커밋 전에 반드시 작성 완료할 것.

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
- **변경 이력**: `docs/CHANGELOG.md` — Claude Code가 기록하는 구현 이력

### Claude Code 자동 구현 흐름

1. `docs/BRIDGE_SPEC.md`를 읽어 안전 게이트 규칙을 로드
2. `docs/proposals/`에서 `상태: ready` 인 제안서를 날짜순으로 수집
3. 각 제안서에 대해 안전 게이트 검증 (금지 영역, 파라미터 범위, 코드 변경 규칙)
4. 통과 시 → 변경 스펙에 따라 코드 수정 → pytest + mypy + ruff 검증
5. 전부 pass → `implemented` 처리, `docs/CHANGELOG.md`에 기록
6. 하나라도 fail → `git restore`로 원복, `failed` 처리
7. 구현된 것이 있으면 `launchctl stop/start com.kis.autotrader`로 재시작
