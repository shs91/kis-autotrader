# [Plan] Worker 분리 — 매매 엔진 I/O 비동기화

## 메타데이터
- 작성일: 2026-04-15
- 우선순위: high
- 의존성: 없음 (기존 시스템에 추가)
- 상태: Draft

## 1. 목표

매매 엔진(engine.py)에서 외부 네트워크 호출과 무거운 I/O 작업을 별도 Worker 프로세스로
분리하여, 네트워크 장애 시에도 매매 로직이 영향받지 않도록 한다.

## 2. 배경

- 2026-04-14: 네트워크 단절로 15:40 post_market의 Google Calendar 등록 실패
- post_market에서 Calendar API(1~2초) + Telegram API(0.5~1초) + DB 집계(40~250ms)가
  순차 실행되어 장 마감 후 작업이 지연됨
- 장중 스크리닝 API 호출이 매매 사이클과 rate limiter를 공유하여 경합 발생
- 매매 체결 후 DB 기록(30~90ms/건)이 다음 종목 분석을 지연시킴

## 3. 범위

### 3.1 In Scope

- [ ] PostgreSQL task_queue 테이블 (Outbox 패턴)
- [ ] Redis 도입 (Rate Limiter 공유 + Worker Queue 보조)
- [ ] Worker 프로세스 (src/worker/)
- [ ] Phase 1: 외부 네트워크 작업 분리 (Calendar, Telegram, 일일집계/포트폴리오)
- [ ] Phase 2: 매매 DB 기록 Queue화 (Trade, Signal, Metric)
- [ ] Phase 3: 스크리닝 API 분리 (별도 Worker + Redis Rate Limiter)

### 3.2 Out of Scope

- Kafka, RabbitMQ 등 외부 메시지 브로커 (과도한 인프라)
- Telegram Bot 폴링 분리 (이미 asyncio.Task로 백그라운드 실행)
- 일일 리포트 생성 분리 (이미 별도 스크립트)
- 패치노트 캘린더 등록 분리 (이미 별도 스크립트)

## 4. 요구사항

### 4.1 기능 요구사항

| ID | 요구사항 | 우선순위 | Phase |
|----|----------|----------|-------|
| FR-01 | task_queue 테이블로 비동기 태스크 관리 (PENDING→RUNNING→COMPLETED/FAILED) | High | 1 |
| FR-02 | Worker가 큐를 폴링하여 태스크 실행 (30초 간격) | High | 1 |
| FR-03 | 실패한 태스크 자동 재시도 (exponential backoff, 최대 5회) | High | 1 |
| FR-04 | Calendar 이벤트 등록을 Queue 경유로 변경 | High | 1 |
| FR-05 | Telegram 알림 전송을 Queue 경유로 변경 | High | 1 |
| FR-06 | 일일 요약 집계(DailySummary)를 Queue 경유로 변경 | Medium | 1 |
| FR-07 | 포트폴리오 동기화를 Queue 경유로 변경 | Medium | 1 |
| FR-08 | 매매/시그널/메트릭 DB 기록을 Queue 경유로 변경 | Medium | 2 |
| FR-09 | DB 기록 배치 INSERT 지원 (여러 건 모아서 1회 트랜잭션) | Low | 2 |
| FR-10 | 스크리닝을 별도 Worker로 분리 | High | 3 |
| FR-11 | Redis 기반 분산 Rate Limiter (프로세스 간 공유) | High | 3 |
| FR-12 | 시간대별 API 호출 할당량 동적 배분 | Medium | 3 |

### 4.2 비기능 요구사항

| 카테고리 | 기준 | 측정 방법 |
|----------|------|-----------|
| 신뢰성 | 태스크 유실 0건 (DB 기반 영속 큐) | task_queue 테이블 감사 |
| 성능 | post_market 완료 시간 3초 이상 단축 | 로그 타임스탬프 비교 |
| 성능 | 매매 사이클 응답 시간 30~90ms 단축/건 | 사이클 완료 로그 |
| 가용성 | 네트워크 장애 시 매매 로직 정상 동작 | 네트워크 차단 테스트 |
| 가용성 | Worker 다운 시 태스크 누적 후 복구 시 일괄 처리 | Worker 재시작 테스트 |
| 호환성 | 기존 테스트 114개 모두 통과 유지 | pytest |

## 5. 아키텍처

### 5.1 전체 구조

```
┌──────────────────────────────────────────────────────────────┐
│                     PostgreSQL                                │
│  ┌─────────────┐  ┌──────────────────────────────────────┐   │
│  │ 기존 테이블  │  │ task_queue (Outbox 패턴)             │   │
│  │ trades      │  │  id, task_type, payload(JSONB),      │   │
│  │ signals     │  │  status, retry_count, max_retries,   │   │
│  │ orders ...  │  │  scheduled_at, started_at,           │   │
│  └─────────────┘  │  completed_at, error_message,        │   │
│                    │  idempotency_key                     │   │
│                    └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                          ▲         ▲
         enqueue()        │         │  poll & execute
                          │         │
┌─────────────────┐       │    ┌────┴────────────┐
│   메인 엔진     │───────┘    │   Worker        │
│  (매매 전용)    │            │  (I/O 처리)     │
│                 │            │                  │
│ • 시세 조회     │            │ • Calendar API   │
│ • 전략 분석     │            │ • Telegram API   │
│ • 주문 실행     │            │ • DB 집계        │
│ • Queue INSERT  │            │ • DB 기록 배치   │
└─────────────────┘            └──────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                       Redis                                   │
│  kis_rate:{second} → atomic counter (Rate Limiter)           │
│  kis_quota:{role}  → 할당량 (main: 80%, screener: 20%)      │
└──────────────────────────────────────────────────────────────┘
                     ▲              ▲
                     │              │
           ┌─────────┴───┐  ┌──────┴──────────┐
           │  메인 엔진   │  │ Screening Worker │
           │  초당 16건   │  │ 초당 4건         │
           │  (실전 기준)  │  │ (Phase 3)        │
           └─────────────┘  └─────────────────┘
```

### 5.2 태스크 타입

| task_type | payload 예시 | Phase |
|-----------|-------------|-------|
| `calendar_event` | `{trade_date, total_pl, rate, details}` | 1 |
| `telegram_notify` | `{notify_type, message_data}` | 1 |
| `daily_summary` | `{report_date}` | 1 |
| `sync_portfolio` | `{holdings: [...]}` | 1 |
| `record_trade` | `{stock_code, trade_type, qty, price, ...}` | 2 |
| `record_signal` | `{stock_code, signal_type, confidence, ...}` | 2 |
| `record_metric` | `{metric_type, detail}` | 2 |
| `run_screening` | `{top_n, exclude_codes, cycle_number}` | 3 |

### 5.3 Rate Limiter 설계 (Phase 3)

```
시간대별 할당:
────────────────────────────────────────────────
08:30~08:55  스크리닝 100%  (장 시작 전 집중 발굴)
09:00~15:20  메인 80% + 스크리닝 20%  (장중)
15:40~       Worker 100%  (장 마감 후)
────────────────────────────────────────────────

Redis 키 구조:
  kis_rate:{unix_second}  → INCR + EXPIRE 2초
  kis_quota:main          → 동적 할당량
  kis_quota:screener      → 동적 할당량
```

## 6. 신규 파일 구조

```
src/worker/
├── __init__.py
├── queue.py              # TaskQueue: enqueue/dequeue/update (PostgreSQL)
├── runner.py             # WorkerRunner: 메인 루프, 폴링, 에러 처리
├── handlers.py           # 태스크 타입별 핸들러 (calendar, telegram, db 등)
└── screener.py           # 스크리닝 전용 Worker (Phase 3)

src/api/
└── rate_limiter.py       # RedisRateLimiter 추가 (기존 TokenBucket 병행)

alembic/versions/
└── xxxx_add_task_queue.py  # task_queue 마이그레이션
```

### 6.1 기존 파일 변경

| 파일 | 변경 내용 | Phase |
|------|-----------|-------|
| `src/engine.py` | 직접 호출 → `queue.enqueue()` | 1, 2, 3 |
| `src/db/models.py` | TaskQueue 모델 추가 | 1 |
| `src/config.py` | Redis URL, Worker 설정 추가 | 1 |
| `main.py` | Worker 프로세스 시작 로직 | 1 |
| `docker-compose.yml` | Redis 서비스 추가 | 1 |
| `.env.example` | REDIS_URL 추가 | 1 |
| `src/api/rate_limiter.py` | Redis 기반 분산 Rate Limiter | 3 |
| `src/scheduler/jobs.py` | 스크리닝 스케줄 분리 | 3 |

## 7. Phase별 구현 계획

### Phase 1: 인프라 + 외부 네트워크 분리 (2~3일)

```
Day 1:
  - task_queue 테이블 + Alembic 마이그레이션
  - TaskQueue 모델 (src/db/models.py)
  - queue.py: enqueue(), dequeue(), mark_completed(), mark_failed()
  - runner.py: WorkerRunner 메인 루프

Day 2:
  - handlers.py: CalendarEventHandler, TelegramNotifyHandler
  - handlers.py: DailySummaryHandler, SyncPortfolioHandler
  - engine.py 수정: _create_calendar_event() → queue.enqueue()
  - engine.py 수정: notify_daily_summary() → queue.enqueue()

Day 3:
  - docker-compose.yml에 Redis 추가
  - main.py에 Worker 프로세스 시작
  - launchd plist 업데이트 (Worker 프로세스 관리)
  - 테스트 작성 + 통합 테스트
```

### Phase 2: 매매 DB 기록 Queue화 (1~2일)

```
Day 4:
  - handlers.py: RecordTradeHandler, RecordSignalHandler, RecordMetricHandler
  - 배치 INSERT 지원 (여러 건 모아서 1회 트랜잭션)
  - engine.py 수정: _record_*_to_db() → queue.enqueue()
  - idempotency_key로 중복 방지

Day 5:
  - 순서 보장 테스트 (traded_at 타임스탬프 기준)
  - 기존 테스트 114개 통과 확인
```

### Phase 3: 스크리닝 API 분리 (3~4일)

```
Day 6:
  - RedisRateLimiter 구현 (src/api/rate_limiter.py)
  - 기존 TokenBucket과 동일 인터페이스 유지
  - 시간대별 할당량 동적 조정

Day 7:
  - screener.py: ScreeningWorker (별도 프로세스)
  - engine.py에서 _screen_stocks() → DB 조회로 변경
  - screening_results 테이블에서 최신 결과 읽기

Day 8-9:
  - Rate Limiter 프로세스 간 공유 테스트
  - 스크리닝 ↔ 매매 API 호출 경합 해소 확인
  - 전체 통합 테스트
```

## 8. 성공 기준

### 8.1 Phase 1 완료 조건

- [ ] Calendar/Telegram이 Queue 경유로 동작
- [ ] 네트워크 차단 시 매매 정상 + 태스크 큐에 적재
- [ ] 네트워크 복구 시 Worker가 적재된 태스크 자동 처리
- [ ] post_market 완료 시간 2초 이상 단축
- [ ] pytest 전체 통과

### 8.2 Phase 2 완료 조건

- [ ] 매매 체결 후 즉시 다음 종목으로 이동 (DB 기록 대기 없음)
- [ ] DB 기록 누락 0건 (idempotency_key 검증)
- [ ] 매매 사이클 응답 시간 개선 확인
- [ ] pytest 전체 통과

### 8.3 Phase 3 완료 조건

- [ ] 스크리닝이 별도 Worker에서 실행
- [ ] Redis Rate Limiter로 프로세스 간 API 호출 제한 공유
- [ ] 장중 스크리닝 ↔ 매매 API 경합 없음
- [ ] 시간대별 할당량 동적 전환 확인
- [ ] pytest 전체 통과

## 9. 리스크 및 대응

| 리스크 | 영향 | 가능성 | 대응 |
|--------|------|--------|------|
| Worker 프로세스 다운 | 태스크 누적 (매매 무관) | 중간 | launchd 자동 재시작 + 모니터링 |
| Redis 다운 | Rate Limiter 동작 불가 | 낮음 | 로컬 TokenBucket 폴백 |
| DB 기록 Queue 지연 | 실시간 잔고 조회 불일치 | 중간 | 주문/잔고는 KIS API 직접 조회 유지 |
| 태스크 중복 실행 | Calendar 이중 등록 등 | 중간 | idempotency_key로 방지 |
| Phase 3 Rate Limiter 정확도 | API 차단 위험 | 중간 | 보수적 할당 (여유 10% 확보) |

## 10. 환경변수 추가

```env
# Redis
REDIS_URL=redis://localhost:6379/0

# Worker
WORKER_POLL_INTERVAL=30          # 큐 폴링 간격 (초)
WORKER_MAX_RETRIES=5             # 최대 재시도 횟수
WORKER_RETRY_BASE_DELAY=60      # 재시도 기본 대기 (초)
WORKER_BATCH_SIZE=10             # 배치 처리 크기
```

## 11. 다음 단계

1. [ ] Design 문서 작성 (`worker-separation.design.md`)
2. [ ] Phase 1 구현 시작
3. [ ] Phase 1 완료 후 배포 및 검증
4. [ ] Phase 2, 3 순차 진행

## 버전 이력

| 버전 | 날짜 | 변경 | 작성자 |
|------|------|------|--------|
| 0.1 | 2026-04-15 | 초안 작성 | Claude Code |
