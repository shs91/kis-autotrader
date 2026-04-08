# KIS 주식 자동매매 시스템

## 프로젝트 개요

한국투자증권(KIS) OpenAPI를 활용한 주식 자동매매 시스템.
당일 매매 결과를 Google Calendar에 자동 등록하는 기능 포함.

## 기술 스택

- **Language**: Python 3.12+
- **Database**: PostgreSQL + SQLAlchemy + Alembic
- **Scheduler**: APScheduler
- **API**: KIS OpenAPI (한국투자증권)
- **Calendar**: Google Calendar API (google-api-python-client)
- **Test**: pytest
- **Lint/Type**: ruff, mypy

## 디렉토리 구조

```
kis-autotrader/
├── CLAUDE.md
├── .env.example
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── config.py              # 환경변수, 설정값 관리
│   ├── api/                   # [api-engineer 담당]
│   │   ├── __init__.py
│   │   ├── auth.py            # OAuth 인증, 토큰 발급/갱신
│   │   ├── client.py          # KIS API 기본 클라이언트
│   │   ├── rate_limiter.py    # 호출 제한 관리 (Token Bucket)
│   │   ├── order.py           # 주문 API (매수/매도/정정/취소)
│   │   ├── quote.py           # 시세 조회 API
│   │   ├── account.py         # 잔고/계좌 조회 API
│   │   ├── websocket.py       # 실시간 웹소켓 매니저
│   │   └── health.py          # 헬스체크 HTTP 서버
│   ├── strategy/              # [strategy-engineer 담당]
│   │   ├── __init__.py
│   │   ├── base.py            # 매매 전략 추상 클래스
│   │   ├── moving_average.py  # 이동평균 교차 전략
│   │   ├── rsi.py             # RSI 기반 전략
│   │   ├── ensemble.py        # 앙상블 (다중 전략 투표)
│   │   ├── registry.py        # 전략 레지스트리
│   │   ├── selector.py        # 종목별 전략 셀렉터
│   │   ├── macd.py            # MACD 전략
│   │   ├── bollinger.py       # 볼린저밴드 전략
│   │   ├── risk.py            # 리스크 관리 모듈
│   │   └── screener.py        # 종목 스크리닝 (필터+스코어링)
│   ├── db/                    # [db-scheduler-engineer 담당]
│   │   ├── __init__.py
│   │   ├── models.py          # SQLAlchemy 모델
│   │   ├── session.py         # DB 세션 관리
│   │   ├── repository.py      # 데이터 접근 레이어
│   │   ├── analytics.py       # 매매 분석 쿼리
│   │   └── event_logger.py    # 구조화 이벤트 로깅
│   ├── scheduler/             # [db-scheduler-engineer 담당]
│   │   ├── __init__.py
│   │   ├── jobs.py            # APScheduler 작업 정의
│   │   └── holidays.py        # 공휴일/휴장일 판단
│   ├── calendar/              # [calendar-engineer 담당]
│   │   ├── __init__.py
│   │   ├── google_auth.py     # Google OAuth2 인증
│   │   └── event.py           # 캘린더 이벤트 생성
│   ├── notify/                # [team lead 담당]
│   │   ├── __init__.py
│   │   ├── telegram.py        # Telegram 알림 전송
│   │   ├── formatter.py       # 메시지 포매터
│   │   └── bot.py             # Telegram 봇 명령 수신
│   └── utils/
│       ├── __init__.py
│       └── logger.py          # 로깅 설정
├── dashboard/                 # Streamlit 웹 대시보드
│   ├── app.py                 # 메인 대시보드
│   └── pages/
│       ├── trades.py          # 매매 분석
│       ├── performance.py     # 성과 분석
│       ├── signals.py         # 시그널 분석
│       └── risk.py            # 리스크 분석 (MDD, Sharpe, 연패)
├── tests/
│   ├── test_api/
│   ├── test_strategy/
│   ├── test_db/
│   └── test_calendar/
└── main.py                    # 엔트리포인트
```

## 코딩 컨벤션

- Type hints 필수 (모든 함수 시그니처에 적용)
- docstring은 한글로 작성
- 환경변수는 .env 파일로 관리 (python-dotenv)
- 클래스/함수명은 영어, 주석/문서는 한글
- 상수는 대문자 스네이크 케이스 (MAX_RETRY_COUNT)
- 에러는 커스텀 예외 클래스로 정의 (src/utils/exceptions.py)

## 검증 명령어

```bash
pytest tests/                    # 전체 테스트
pytest tests/test_api/ -v        # API 모듈 테스트
python -m mypy src/              # 타입 체크
ruff check src/                  # 린트
```

## 모듈 경계 (에이전트별 담당 영역 - 반드시 준수)

| 디렉토리 | 담당 에이전트 | 비고 |
|-----------|---------------|------|
| src/api/ | api-engineer | KIS API 통신 전담. RateLimiter 여기서 구현 |
| src/strategy/ | strategy-engineer | API 직접 호출 금지. 데이터를 인자로 받음 |
| src/db/, src/scheduler/ | db-scheduler-engineer | 데이터 영속성 + 스케줄링 |
| src/calendar/ | calendar-engineer | Google Calendar 연동 전담 |
| src/config.py, src/utils/ | team lead | 공통 설정/유틸리티 |
| main.py | team lead | 최종 조합 및 엔트리포인트 |

**다른 에이전트의 담당 디렉토리 파일을 직접 수정하지 말 것.**
인터페이스 조율이 필요하면 teammate 간 메시지로 합의할 것.

---

## ⚠️ KIS API 호출 제한 정책 (전 에이전트 필독)

### 1. REST API 초당 호출 제한

- **신규 고객**: 신청 후 3일간 **초당 3건** 제한 → 이후 기본 유량 상향
- **모의투자 계좌**: 해당 없음 (기본 유량 유지)
- **서비스 해지 후 재등록 시 신규로 간주됨**

구현 필수 사항:
- `src/api/rate_limiter.py`에 Token Bucket 방식 Rate Limiter 구현
- 초당 최대 호출 수를 **설정값으로 관리** (기본값: 3건/초)
- 호출 간 최소 간격: **334ms 이상**
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

구현 필수 사항:
- 재연결 시 **exponential backoff** 적용 (5초 → 10초 → 20초 → 최대 60초)
- 최대 재연결 시도 횟수 제한 (기본 5회, 이후 알림 후 중단)
- 종목 구독 후 **수신 확인(heartbeat/첫 데이터)** 확인 후 다음 동작
- 구독 등록/해제에 **디바운싱** 적용 (최소 1초 간격)
- 연결 상태 머신 구현: DISCONNECTED → CONNECTING → CONNECTED → SUBSCRIBING → ACTIVE

### 3. 공통 안전장치

- API 에러 응답 처리:
  - `429 Too Many Requests` → Rate Limit 대기 후 재시도
  - `5xx` → exponential backoff 재시도 (최대 3회)
  - 그 외 에러 → 로그 기록 후 예외 발생
- 일일 최대 API 호출 횟수 상한 설정 (config.py에서 관리)
- 모든 API 호출/응답을 로그에 기록 (호출 시각, 엔드포인트, 응답코드)
- 비정상 호출 패턴 감지 시 자동 중단 (circuit breaker)

### 4. 스케줄러 호출 시 주의 (db-scheduler-engineer 필독)

- 시세 조회 주기를 **초당 3건 이하**로 설정
- 종목 수 × 조회 빈도 계산 필수
  - 예: 10종목 모니터링 시 → 최소 **3.4초 간격**으로 순회
  - 예: 5종목 모니터링 시 → 최소 **1.7초 간격**으로 순회
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

```env
# KIS API
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_number
KIS_ACCOUNT_PRODUCT_CODE=01
KIS_ENV=virtual  # virtual(모의) 또는 real(실전)

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/kis_trader

# Google Calendar
GOOGLE_CALENDAR_ID=your_calendar_id
GOOGLE_CREDENTIALS_PATH=credentials.json

# Rate Limit
API_RATE_LIMIT_PER_SECOND=3
API_DAILY_CALL_LIMIT=10000
WS_MAX_RECONNECT_ATTEMPTS=5
WS_RECONNECT_BASE_DELAY=5

# Trading
MAX_LOSS_RATE=0.03
MAX_POSITION_RATIO=0.2
DAILY_TRADE_LIMIT=10
```

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
