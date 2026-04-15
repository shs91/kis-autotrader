# Worker 분리 Design Document

> **Summary**: 매매 엔진에서 외부 I/O 작업을 PostgreSQL Outbox + Redis 기반 Worker로 분리
>
> **Project**: kis-autotrader
> **Date**: 2026-04-15
> **Status**: Draft
> **Planning Doc**: [worker-separation.plan.md](../../01-plan/features/worker-separation.plan.md)

---

## 1. 설계 목표

1. 매매 엔진은 **시세 조회 → 전략 분석 → 주문 실행**에만 집중
2. 외부 네트워크 호출(Calendar, Telegram)은 Worker가 비동기 처리
3. 네트워크 장애 시 태스크가 DB에 영속되어 복구 후 자동 재시도
4. 프로세스 간 API Rate Limiter를 Redis로 공유

### 설계 원칙

- 기존 인터페이스 최소 변경 (engine.py의 호출부만 교체)
- 각 Phase 독립 배포 가능 (Phase 1만으로도 동작)
- 태스크 실패가 매매에 영향 없음 (fire-and-forget)
- 중복 실행 방지 (idempotency_key)

---

## 2. 아키텍처

### 2.1 전체 구조

```
┌──────────────────────────────────────────────────────────────────┐
│                        PostgreSQL                                 │
│                                                                   │
│  기존 테이블              task_queue (신규)                       │
│  ┌─────────────┐          ┌──────────────────────────────────┐   │
│  │ trades      │          │ id (PK)                          │   │
│  │ signals     │          │ task_type     (VARCHAR 50)       │   │
│  │ orders      │          │ payload       (JSONB)            │   │
│  │ portfolios  │          │ status        (ENUM)             │   │
│  │ daily_*     │          │ priority      (INT, default 0)   │   │
│  │ ...         │          │ idempotency_key (VARCHAR, UQ)    │   │
│  └─────────────┘          │ retry_count   (INT, default 0)   │   │
│                           │ max_retries   (INT, default 5)   │   │
│                           │ error_message (TEXT, nullable)    │   │
│                           │ scheduled_at  (TIMESTAMPTZ)      │   │
│                           │ started_at    (TIMESTAMPTZ)      │   │
│                           │ completed_at  (TIMESTAMPTZ)      │   │
│                           │ created_at    (TIMESTAMPTZ)      │   │
│                           └──────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
          ▲ enqueue()                    ▲ poll()
          │                              │
┌─────────┴─────────┐          ┌────────┴──────────┐
│   메인 엔진        │          │   I/O Worker       │
│  (프로세스 A)      │          │  (프로세스 B)      │
│                    │          │                    │
│ • 시세 조회        │          │ • calendar_event   │
│ • 전략 분석        │          │ • telegram_notify  │
│ • 주문 실행        │          │ • daily_summary    │
│ • queue.enqueue()  │          │ • sync_portfolio   │
│                    │          │ • record_trade     │  ← Phase 2
│                    │          │ • record_signal    │
│                    │          │ • record_metric    │
└────────────────────┘          └────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                          Redis                                    │
│                                                                   │
│  kis_rate:{unix_second}  → INCR (atomic 초당 카운터)             │
│  kis_quota:main          → 16 (실전 80%)                         │
│  kis_quota:screener      → 4  (실전 20%)                         │
│  kis_daily_count         → 일일 API 호출 합산                    │
└──────────────────────────────────────────────────────────────────┘
          ▲                              ▲
          │                              │
┌─────────┴─────────┐          ┌────────┴──────────┐
│   메인 엔진        │          │ Screening Worker   │  ← Phase 3
│  (quota: main)     │          │ (quota: screener)  │
└────────────────────┘          └────────────────────┘
```

### 2.2 데이터 흐름

```
[Phase 1] 외부 네트워크 작업
  매매 완료 → engine: queue.enqueue("calendar_event", {...})
           → engine: queue.enqueue("telegram_notify", {...})
           → DB task_queue INSERT (PENDING)
           → Worker: 30초 간격 폴링 → PENDING 태스크 실행
           → 성공: COMPLETED / 실패: retry_count++ → 재시도

[Phase 2] DB 기록
  매수 체결 → engine: queue.enqueue("record_trade", {...})
           → Worker: 배치 모드로 모아서 1회 트랜잭션 INSERT

[Phase 3] 스크리닝
  스케줄러 → screener worker: KIS API 거래량순위 조회
          → 필터링 + 스코어링
          → screening_results INSERT
          → 메인 엔진: screening_results SELECT (최신 결과 읽기)
```

### 2.3 의존성

| 컴포넌트 | 의존 대상 | 용도 |
|----------|----------|------|
| `src/worker/queue.py` | `src/db/session.py`, `src/db/models.py` | DB 세션, TaskQueue 모델 |
| `src/worker/runner.py` | `src/worker/queue.py`, `src/worker/handlers.py` | 큐 폴링 + 핸들러 디스패치 |
| `src/worker/handlers.py` | `src/calendar/`, `src/notify/`, `src/db/repository.py` | 실제 작업 수행 |
| `src/worker/screener.py` | `src/api/quote.py`, `src/strategy/`, `src/api/rate_limiter.py` | 스크리닝 실행 |
| `src/api/rate_limiter.py` | `redis` | 분산 Rate Limiter (Phase 3) |

---

## 3. 데이터 모델

### 3.1 TaskQueue 모델

```python
class TaskStatus(enum.Enum):
    """태스크 상태."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD = "DEAD"          # max_retries 초과

class TaskQueue(Base):
    """비동기 태스크 큐 테이블."""
    __tablename__ = "task_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.PENDING, index=True, nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
```

### 3.2 DB 스키마

```sql
CREATE TYPE task_status_enum AS ENUM (
    'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'DEAD'
);

CREATE TABLE task_queue (
    id              SERIAL PRIMARY KEY,
    task_type       VARCHAR(50) NOT NULL,
    payload         JSONB NOT NULL,
    status          task_status_enum NOT NULL DEFAULT 'PENDING',
    priority        INTEGER NOT NULL DEFAULT 0,
    idempotency_key VARCHAR(255) UNIQUE,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 5,
    error_message   TEXT,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 인덱스: Worker 폴링 최적화
CREATE INDEX ix_task_queue_poll ON task_queue (status, priority DESC, scheduled_at)
    WHERE status IN ('PENDING', 'FAILED');

-- 인덱스: 정리용
CREATE INDEX ix_task_queue_completed ON task_queue (completed_at)
    WHERE status = 'COMPLETED';
```

### 3.3 태스크 상태 전이

```
                    enqueue()
                       │
                       ▼
                   ┌────────┐
                   │PENDING │
                   └───┬────┘
                       │  Worker poll
                       ▼
                   ┌────────┐
          ┌────────│RUNNING │────────┐
          │        └────────┘        │
          │ 성공                     │ 실패
          ▼                          ▼
    ┌───────────┐          ┌──────────────┐
    │ COMPLETED │          │   FAILED     │
    └───────────┘          └──────┬───────┘
                                  │
                    retry_count < max_retries?
                    ├── Yes → PENDING (재시도)
                    └── No  → DEAD (포기)
```

---

## 4. 모듈 상세 설계

### 4.1 `src/worker/queue.py` — 태스크 큐

```python
class TaskQueueService:
    """PostgreSQL 기반 태스크 큐 서비스."""

    def enqueue(
        self,
        task_type: str,
        payload: dict,
        priority: int = 0,
        idempotency_key: str | None = None,
        max_retries: int = 5,
        scheduled_at: datetime | None = None,
    ) -> int:
        """태스크를 큐에 추가한다.

        Returns:
            생성된 태스크 ID.
        """

    def dequeue(self, batch_size: int = 1) -> list[TaskQueue]:
        """실행 가능한 태스크를 가져온다.

        SELECT ... WHERE status IN ('PENDING', 'FAILED')
          AND scheduled_at <= NOW()
          AND retry_count < max_retries
        ORDER BY priority DESC, scheduled_at ASC
        LIMIT batch_size
        FOR UPDATE SKIP LOCKED
        """

    def mark_running(self, task_id: int) -> None:
        """태스크를 RUNNING 상태로 변경한다."""

    def mark_completed(self, task_id: int) -> None:
        """태스크를 COMPLETED 상태로 변경한다."""

    def mark_failed(self, task_id: int, error: str) -> None:
        """태스크를 FAILED로 변경하고 retry_count를 증가한다.
        max_retries 초과 시 DEAD로 변경한다."""

    def cleanup_old_tasks(self, days: int = 7) -> int:
        """완료된 태스크 중 N일 이상 지난 것을 삭제한다."""
```

**핵심 설계 포인트:**
- `FOR UPDATE SKIP LOCKED`: 다중 Worker 확장 시에도 동일 태스크 중복 처리 방지
- `idempotency_key`: 동일 키로 중복 enqueue 방지 (예: `calendar_2026-04-15`)
- `priority`: 높은 값이 먼저 실행 (매매 기록 > 캘린더 > 메트릭)

### 4.2 `src/worker/runner.py` — Worker 메인 루프

```python
class WorkerRunner:
    """Worker 메인 프로세스."""

    def __init__(
        self,
        poll_interval: int = 30,
        batch_size: int = 10,
    ) -> None:
        self._queue = TaskQueueService()
        self._handlers: dict[str, TaskHandler] = {}
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._running = False

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """태스크 타입별 핸들러를 등록한다."""

    async def run(self) -> None:
        """Worker 메인 루프.

        1. task_queue에서 PENDING/FAILED 태스크를 batch로 조회
        2. 각 태스크의 task_type에 맞는 핸들러 호출
        3. 성공/실패 상태 업데이트
        4. poll_interval만큼 대기 후 반복
        """

    async def _process_task(self, task: TaskQueue) -> None:
        """단일 태스크를 처리한다.

        1. mark_running()
        2. handler.execute(task.payload)
        3. 성공 → mark_completed()
        4. 실패 → mark_failed(error_message)
        """
```

**재시도 정책 (exponential backoff):**
```
retry 1: 60초 후 (scheduled_at = now + 60s)
retry 2: 120초 후
retry 3: 240초 후
retry 4: 480초 후
retry 5: DEAD (포기, 로그 기록)
```

### 4.3 `src/worker/handlers.py` — 태스크 핸들러

```python
class TaskHandler(ABC):
    """태스크 핸들러 추상 클래스."""

    @abstractmethod
    async def execute(self, payload: dict) -> None:
        """태스크를 실행한다."""


class CalendarEventHandler(TaskHandler):
    """Google Calendar 이벤트 등록 핸들러."""

    async def execute(self, payload: dict) -> None:
        """payload: {trade_date, total_profit_loss, profit_rate,
                     execution_count, details_json}"""
        auth = GoogleCalendarAuth()
        service = auth.get_service()
        creator = CalendarEventCreator(service=service)
        creator.create_daily_report_event(
            trade_date=date.fromisoformat(payload["trade_date"]),
            total_profit_loss=payload["total_profit_loss"],
            profit_rate=payload["profit_rate"],
            execution_count=payload["execution_count"],
            details_json=payload["details_json"],
        )


class TelegramNotifyHandler(TaskHandler):
    """Telegram 알림 전송 핸들러."""

    async def execute(self, payload: dict) -> None:
        """payload: {notify_type, message_data}
        notify_type: buy, sell, daily_summary, error, system
        """
        notifier = TelegramNotifier()
        method = getattr(notifier, f"notify_{payload['notify_type']}")
        await method(**payload["message_data"])


class DailySummaryHandler(TaskHandler):
    """일일 요약 집계 핸들러."""

    async def execute(self, payload: dict) -> None:
        """payload: {report_date}"""
        with get_session() as session:
            repo = DailySummaryRepository(session)
            repo.upsert_daily_summary(
                date.fromisoformat(payload["report_date"])
            )


class SyncPortfolioHandler(TaskHandler):
    """포트폴리오 동기화 핸들러."""

    async def execute(self, payload: dict) -> None:
        """payload: {holdings: [{stock_code, quantity, avg_price, current_price}]}"""
        with get_session() as session:
            stock_repo = StockRepository(session)
            portfolio_repo = PortfolioRepository(session)
            for h in payload["holdings"]:
                stock = stock_repo.get_by_code(h["stock_code"])
                if stock is None:
                    stock = stock_repo.create(
                        h["stock_code"], h["stock_code"], "UNKNOWN"
                    )
                portfolio_repo.upsert(
                    stock_id=stock.id,
                    quantity=h["quantity"],
                    avg_price=h["avg_price"],
                    current_price=h["current_price"],
                )


class RecordTradeHandler(TaskHandler):
    """매매 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict) -> None:
        """payload: {stock_code, stock_name, trade_type, quantity,
                     price, total_amount, reason, signal_type,
                     profit_loss_pct, profit_loss_amount, cycle_number,
                     traded_at}"""
        with get_session() as session:
            repo = TradeRepository(session)
            repo.create(**payload)


class RecordSignalHandler(TaskHandler):
    """시그널 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict) -> None:
        with get_session() as session:
            repo = SignalRepository(session)
            repo.create(**payload)


class RecordMetricHandler(TaskHandler):
    """시스템 메트릭 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict) -> None:
        with get_session() as session:
            repo = SystemMetricRepository(session)
            repo.record_metric(**payload)
```

### 4.4 `src/worker/screener.py` — 스크리닝 Worker (Phase 3)

```python
class ScreeningWorker:
    """스크리닝 전용 Worker.

    메인 매매 엔진과 별도 프로세스로 실행되며,
    Redis Rate Limiter를 통해 API 호출 할당량을 관리한다.
    """

    def __init__(self) -> None:
        self._auth = KISAuth()
        self._client = KISClient(
            auth=self._auth,
            limiter=RedisRateLimiter(role="screener"),  # Redis 기반
        )
        self._quote = QuoteAPI(self._client)
        self._screener = StockScreener()
        self._selector = StrategySelector()

    async def run_screening(self) -> list[str]:
        """스크리닝을 실행하고 결과를 DB에 저장한다.

        1. KIS API 거래량 순위 조회
        2. 필터링 + 전략 분석 + 스코어링
        3. screening_results 테이블에 INSERT
        4. 발굴 종목 코드 리스트 반환
        """
```

### 4.5 `src/api/rate_limiter.py` — Redis Rate Limiter (Phase 3)

```python
class RedisRateLimiter:
    """Redis 기반 분산 Rate Limiter.

    기존 TokenBucket과 동일 인터페이스(acquire)를 제공하며,
    프로세스 간 API 호출 제한을 공유한다.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        role: str = "main",
    ) -> None:
        self._redis = redis.from_url(redis_url or settings.redis.url)
        self._role = role  # "main" or "screener"
        self._daily_count_key = "kis_daily_count"

    async def acquire(self) -> None:
        """API 호출 권한을 획득한다.

        1. Redis INCR로 현재 초의 호출 수 확인
        2. 역할별 할당량(quota) 비교
        3. 초과 시 다음 초까지 대기
        4. 일일 카운터 증가
        """
        # 일일 한도 확인
        daily = await self._redis.get(self._daily_count_key)
        if daily and int(daily) >= settings.rate_limit.daily_limit:
            raise DailyLimitExceededError(...)

        # 초당 호출 제한 (역할별 할당량)
        second_key = f"kis_rate:{int(time.time())}"
        count = await self._redis.incr(second_key)
        if count == 1:
            await self._redis.expire(second_key, 2)

        quota_key = f"kis_quota:{self._role}"
        quota = int(await self._redis.get(quota_key) or self._default_quota())
        if count > quota:
            await asyncio.sleep(1.0)
            # 재시도
            return await self.acquire()

        # 일일 카운터 증가
        await self._redis.incr(self._daily_count_key)

    def _default_quota(self) -> int:
        """역할별 기본 할당량."""
        total = settings.rate_limit.per_second
        if self._role == "screener":
            return max(1, total // 5)      # 20%
        return total - max(1, total // 5)  # 80%

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 횟수 (동기 조회)."""
        val = self._redis.get(self._daily_count_key)
        return int(val) if val else 0

    @property
    def daily_limit(self) -> int:
        return settings.rate_limit.daily_limit

    def log_daily_count(self) -> None:
        logger.info(
            "일일 API 호출 횟수: %d/%d",
            self.daily_count, self.daily_limit,
        )
```

**시간대별 할당량 전환 (scheduler에서 호출):**
```python
async def update_quota(redis, phase: str) -> None:
    """시간대에 따라 할당량을 동적 조정한다."""
    total = settings.rate_limit.per_second
    if phase == "pre_market":      # 08:30~08:55
        await redis.set("kis_quota:main", 0)
        await redis.set("kis_quota:screener", total)
    elif phase == "market_open":   # 09:00~15:20
        await redis.set("kis_quota:main", int(total * 0.8))
        await redis.set("kis_quota:screener", int(total * 0.2))
    elif phase == "post_market":   # 15:40~
        await redis.set("kis_quota:main", total)
        await redis.set("kis_quota:screener", 0)
```

---

## 5. engine.py 변경 설계

### 5.1 Phase 1 변경 (외부 네트워크)

**Before:**
```python
# engine.py post_market()
self._create_calendar_event(balance, executions)
await self._notifier.notify_daily_summary(...)
self._upsert_daily_summary()
self._sync_portfolio(balance)
```

**After:**
```python
# engine.py post_market()
self._enqueue_calendar_event(balance)
self._enqueue_telegram_daily_summary(balance, executions)
self._enqueue_daily_summary()
self._enqueue_sync_portfolio(balance)
```

각 `_enqueue_*` 메서드는 `queue.enqueue()`를 호출하여 DB INSERT만 수행한다.
실제 외부 API 호출은 Worker가 처리한다.

### 5.2 Phase 2 변경 (DB 기록)

**Before:**
```python
# engine.py _execute_buy() 내부
self._record_order_to_db(stock_code, "BUY", ...)
self._record_trade_to_db(stock_code, TradeType.BUY, ...)
await self._notifier.notify_buy(...)
```

**After:**
```python
# engine.py _execute_buy() 내부
self._queue.enqueue("record_trade", {...}, priority=10)
self._queue.enqueue("telegram_notify", {"notify_type": "buy", ...}, priority=5)
```

**우선순위 체계:**

| priority | 용도 | 이유 |
|----------|------|------|
| 10 | 매매 기록 (trade, order) | 데이터 정합성 최우선 |
| 5 | 시그널/메트릭 기록 | 분석 데이터 |
| 3 | Telegram 알림 | 사용자 인지 |
| 1 | Calendar 이벤트, 집계 | 나중에 처리해도 됨 |

### 5.3 Phase 3 변경 (스크리닝)

**Before:**
```python
# engine.py run_trading_cycle() 내부
await self._screen_stocks()  # KIS API 직접 호출
```

**After:**
```python
# engine.py run_trading_cycle() 내부
new_codes = self._read_screening_results()  # DB 조회만
self._screened_codes.update(new_codes)
```

스크리닝 Worker가 별도 프로세스에서 주기적으로 실행하고,
메인 엔진은 `screening_results` 테이블에서 최신 결과만 읽는다.

---

## 6. 프로세스 관리

### 6.1 프로세스 구성

| 프로세스 | 파일 | launchd ID | Phase |
|----------|------|------------|-------|
| 매매 엔진 | `main.py` | `com.kis.autotrader` | 기존 |
| I/O Worker | `main.py --worker` | `com.kis.autotrader` 내부 | 1 |
| Screening Worker | `main.py --screener` | `com.kis.autotrader` 내부 | 3 |

### 6.2 main.py 시작 방식

```python
# main.py
async def main() -> None:
    engine = TradingEngine()
    worker = WorkerRunner()
    worker.register_handler("calendar_event", CalendarEventHandler())
    worker.register_handler("telegram_notify", TelegramNotifyHandler())
    # ... 핸들러 등록

    # 매매 엔진 + Worker를 하나의 프로세스에서 병렬 실행
    await asyncio.gather(
        engine.start(),
        worker.run(),
        # screener.run(),  # Phase 3
    )
```

**설계 선택: 단일 프로세스 내 asyncio.Task로 실행**
- Worker가 가벼우므로 별도 프로세스 불필요
- launchd 설정 변경 없음
- 메인 엔진 재시작 시 Worker도 함께 재시작

---

## 7. Redis 설정

### 7.1 docker-compose.yml 추가

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru

volumes:
  redis_data:
```

### 7.2 로컬 개발 (Docker 없이)

```bash
brew install redis
brew services start redis
```

### 7.3 환경변수

```env
REDIS_URL=redis://localhost:6379/0
```

### 7.4 Redis 키 목록

| 키 패턴 | 용도 | TTL | Phase |
|---------|------|-----|-------|
| `kis_rate:{unix_second}` | 초당 API 호출 카운터 | 2초 | 3 |
| `kis_quota:main` | 메인 엔진 초당 할당량 | 없음 | 3 |
| `kis_quota:screener` | 스크리닝 초당 할당량 | 없음 | 3 |
| `kis_daily_count` | 일일 API 호출 합산 | 자정 리셋 | 3 |

---

## 8. 에러 처리

### 8.1 재시도 정책

| 에러 유형 | 재시도 | 대기 시간 |
|-----------|:------:|-----------|
| 네트워크 에러 (ConnectionError) | O | exponential backoff |
| 인증 에러 (AuthenticationError) | O | 5분 (토큰 갱신 대기) |
| API 429 (Rate Limit) | O | 60초 |
| API 5xx (서버 에러) | O | exponential backoff |
| 데이터 에러 (ValueError 등) | X | DEAD 처리 |
| DB 에러 (IntegrityError 등) | X | DEAD 처리 |

### 8.2 Dead Letter 처리

`status = DEAD`인 태스크는 자동 처리하지 않는다.
- `scripts/query_analytics.py`에 dead task 조회 기능 추가
- Telegram으로 DEAD 태스크 발생 알림 (Worker 내부에서 직접 전송)

### 8.3 Redis 다운 시 폴백

```python
class HybridRateLimiter:
    """Redis 우선, 실패 시 로컬 TokenBucket 폴백."""

    def __init__(self, role: str = "main"):
        self._redis_limiter = RedisRateLimiter(role=role)
        self._local_limiter = RateLimiter()  # 기존 구현

    async def acquire(self) -> None:
        try:
            await self._redis_limiter.acquire()
        except (ConnectionError, TimeoutError):
            logger.warning("Redis 연결 실패, 로컬 Rate Limiter로 폴백")
            await self._local_limiter.acquire()
```

---

## 9. 테스트 계획

### 9.1 테스트 범위

| 유형 | 대상 | 도구 |
|------|------|------|
| 단위 테스트 | TaskQueueService, 각 Handler | pytest + SQLite in-memory |
| 단위 테스트 | RedisRateLimiter | pytest + fakeredis |
| 통합 테스트 | engine → queue → worker 흐름 | pytest + PostgreSQL |
| 통합 테스트 | 스크리닝 Worker + Redis Rate Limiter | pytest + fakeredis |

### 9.2 핵심 테스트 케이스

- [ ] `test_enqueue_dequeue`: 태스크 큐 기본 CRUD
- [ ] `test_idempotency`: 동일 key 중복 enqueue 방지
- [ ] `test_retry_on_failure`: 실패 시 exponential backoff 재시도
- [ ] `test_dead_on_max_retries`: max_retries 초과 시 DEAD 전환
- [ ] `test_skip_locked`: 동시 dequeue 시 중복 처리 방지
- [ ] `test_calendar_handler`: Calendar API mock으로 핸들러 동작 확인
- [ ] `test_telegram_handler`: Telegram API mock으로 핸들러 동작 확인
- [ ] `test_batch_insert`: 다중 trade 기록 배치 INSERT
- [ ] `test_redis_rate_limiter`: 초당 할당량 준수 확인
- [ ] `test_redis_fallback`: Redis 다운 시 로컬 폴백 동작
- [ ] `test_quota_switch`: 시간대별 할당량 전환

---

## 10. 구현 순서

### Phase 1 (Day 1~3)

```
1. [ ] src/db/models.py — TaskQueue, TaskStatus 모델 추가
2. [ ] alembic revision — task_queue 마이그레이션 생성 + 적용
3. [ ] src/worker/__init__.py — 패키지 초기화
4. [ ] src/worker/queue.py — TaskQueueService 구현
5. [ ] src/worker/handlers.py — CalendarEventHandler, TelegramNotifyHandler,
       DailySummaryHandler, SyncPortfolioHandler
6. [ ] src/worker/runner.py — WorkerRunner 메인 루프
7. [ ] src/engine.py — post_market() 내 직접 호출을 enqueue로 교체
8. [ ] src/config.py — Worker 관련 설정 추가
9. [ ] main.py — Worker 시작 로직 추가 (asyncio.gather)
10. [ ] docker-compose.yml — Redis 서비스 추가
11. [ ] .env.example — REDIS_URL 추가
12. [ ] tests/test_worker/ — 단위 + 통합 테스트
```

### Phase 2 (Day 4~5)

```
13. [ ] src/worker/handlers.py — RecordTradeHandler, RecordSignalHandler,
        RecordMetricHandler 추가
14. [ ] src/engine.py — _record_*_to_db()를 enqueue로 교체
15. [ ] 배치 INSERT 지원 (WorkerRunner에서 같은 타입 모아서 처리)
16. [ ] tests/test_worker/ — DB 기록 관련 테스트
```

### Phase 3 (Day 6~9)

```
17. [ ] src/api/rate_limiter.py — RedisRateLimiter + HybridRateLimiter
18. [ ] src/worker/screener.py — ScreeningWorker 구현
19. [ ] src/engine.py — _screen_stocks()를 DB 조회로 교체
20. [ ] src/scheduler/jobs.py — 시간대별 할당량 전환 스케줄 추가
21. [ ] tests/test_worker/ — Rate Limiter + 스크리닝 테스트
22. [ ] 전체 통합 테스트 + 기존 114개 테스트 통과 확인
```

---

## 11. 코딩 컨벤션 적용

| 항목 | 적용 규칙 |
|------|-----------|
| import | `from __future__ import annotations` 모든 파일 |
| type hints | 모든 함수 시그니처 + 반환 타입 |
| docstring | 한글, Google 스타일 |
| 상수 | `WORKER_POLL_INTERVAL`, `TASK_MAX_RETRIES` 등 대문자 스네이크 |
| 설정 | `@dataclass(frozen=True)` 패턴 (`WorkerSettings`, `RedisSettings`) |
| 예외 | `src/utils/exceptions.py`에 `WorkerError`, `TaskExecutionError` 추가 |
| 로깅 | `logger = setup_logger(__name__)` 패턴 |
| 린트 | ruff + mypy strict 통과 필수 |

---

## 버전 이력

| 버전 | 날짜 | 변경 | 작성자 |
|------|------|------|--------|
| 0.1 | 2026-04-15 | 초안 작성 | Claude Code |
