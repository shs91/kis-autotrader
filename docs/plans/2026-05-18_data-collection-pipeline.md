# 데이터 수집 파이프라인 구축 작업 계획

뉴스·공시·실적발표 데이터를 수집·임베딩·저장하여 매매 의사결정 시 LLM이 참조 가능한 RAG 컨텍스트를 제공한다.

- 작성일: 2026-05-18
- 검토 갱신: 2026-05-18 (kis-autotrader 코드베이스 정합성 보강)
- 관련 문서: `docs/BRIDGE_SPEC.md`, `CLAUDE.md`, `.claude/skills/alembic-migration-flow/SKILL.md`

---

## 0. 목표 및 범위

### 목표

뉴스·공시·실적발표 데이터를 수집하여 청킹 → 로컬 임베딩 → pgvector 적재하는 파이프라인을 구축한다. 매매 엔진은 시그널 발생 시 이 데이터를 검색하여 LLM 의사결정 컨텍스트로 사용한다.

### 범위 (이 계획 포함)

- DART OpenAPI 공시 수집
- RSS/네이버 금융 뉴스 수집
- 청킹 + 로컬 임베딩 (BGE-M3)
- pgvector 적재 (HNSW 인덱스)
- APScheduler 통합
- 모니터링 (analytics, 헬스체크, Telegram)

### 범위 외 (별도 계획)

- LLM 추론 통합 (Ollama 클라이언트)
- 하이브리드 검색 retriever
- 매매 엔진 (`src/engine.py`)과의 연동
- 백테스트 시 look-ahead bias 차단 retriever 로직 (단, **모델 컬럼은 본 계획에서 미리 분리**)

### 설계 원칙

- **하네스(.claude/)와 분리**: 데이터 수집은 운영 시스템이고, 하네스는 코드 변경 자동화. 책임 혼재 금지.
- **별도 Worker 프로세스**: 매매 엔진 메모리·실패 격리. 기존 `src/worker/runner.py`(task_queue 폴링)와도 별도 프로세스로 띄움. 통신은 **DB 공유만** (직접 IPC 금지).
- **로컬 임베딩**: 외부 API 의존성 제거, 비용·latency·프라이버시 확보.

---

## 1. 사전 준비 (Phase 0)

### 1.1 외부 의존성

- [ ] DART OpenAPI 키 발급 (https://opendart.fss.or.kr/, 무료, 일 20,000건)
- [ ] DART `corp_code.xml` 다운로드 (종목코드 ↔ corp_code 매핑) → `data/dart/corp_code.xml` 캐싱

### 1.2 인프라

- [ ] PostgreSQL pgvector extension 활성화

  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```

- [ ] **docker-compose.yml의 postgres 이미지 교체**: `postgres:16` → `pgvector/pgvector:pg16`.
      Alembic 마이그레이션 내부에서 `CREATE EXTENSION` 실행해도, 베이스 이미지에 vector가 빌드돼 있어야 한다.
      → BRIDGE_SPEC 금지 영역이므로 **수동 PR**.
- [ ] BGE-M3 모델 **사전 다운로드** (~2GB) — launchd 백그라운드 환경에서는 첫 호출 시 `~/.cache/huggingface/` 쓰기 권한·네트워크가 자주 막힌다.
      개발자 셸에서 미리 실행:

  ```bash
  python -c "from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)"
  ```

- [ ] 디스크 용량 점검 (1년치 데이터 약 5~10GB 예상)

### 1.3 의존성 추가 (`pyproject.toml`)

BRIDGE_SPEC 금지 영역(`pyproject.toml`)이므로 **수동 PR**로 처리.

```toml
"FlagEmbedding>=1.3.0",     # BGE-M3
"feedparser>=6.0.0",        # RSS
"beautifulsoup4>=4.12.0",   # HTML 파싱
"opendartreader>=0.2.0",    # DART 클라이언트 (또는 직접 httpx + KIS api/client 패턴)
"pgvector>=0.3.0",          # SQLAlchemy ↔ pgvector
"pyahocorasick>=2.0.0",     # 종목명 다중 매칭 (false positive 차단)
```

### 1.4 환경변수 추가 (`.env.example` 갱신)

BRIDGE_SPEC 금지 영역이므로 **수동 PR**로 처리.

```env
# DART OpenAPI
NEWS_DART_API_KEY=
NEWS_DART_CORP_CODE_PATH=data/dart/corp_code.xml
NEWS_DART_RATE_LIMIT_PER_SEC=1.0       # 분당 60건 → 안전 마진. 일 20,000건 한도와 분리.

# RSS
NEWS_RSS_FEEDS=yonhap_infomax,edaily_stocks,hankyung_market_insight
NEWS_RSS_USER_AGENT=kis-autotrader/0.1 (+contact: 운영자)

# Embedding
NEWS_EMBEDDING_MODEL=BAAI/bge-m3
NEWS_EMBEDDING_BATCH_SIZE=12
NEWS_EMBEDDING_MAX_TOKENS=8192          # BGE-M3 컨텍스트 상한

# Pipeline
NEWS_COLLECT_INTERVAL_MIN=5
NEWS_CHUNK_RETENTION_DAYS=90
```

`launchd` plist의 `EnvironmentVariables`에는 비밀값을 넣지 않고, **엔트리포인트가 `.env`를 로드**하는 기존 패턴(`src/config.py`)을 그대로 사용한다.

### 1.5 하드웨어 / 메모리 (참고)

대상 환경: M4 Pro 48GB Mac Mini. 자세한 시나리오는 본 문서 **§12 하드웨어 자원 계획**에 통합.

→ **32B는 온디맨드 로딩**, 상시 hot은 14B 또는 7B.

---

## 2. Phase 1 — DB 스키마 및 모델 (2일)

> ⚠️ BRIDGE_SPEC 5파일 제한 때문에 **Phase 1은 두 제안서로 분할**한다.
>
> - **1a**: `models.py`, `alembic/versions/<rev>_news.py`, `tests/test_db/test_news_chunk.py` (3파일)
> - **1b**: `repository.py`, `tests/test_db/test_news_chunk_repo.py` (2파일)

### 2.1 SQLAlchemy 모델 추가

파일: `src/db/models.py`

```python
import enum
from datetime import datetime
from sqlalchemy import (
    BigInteger, DateTime, Enum as SQLEnum, Float, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector


class NewsSourceType(enum.Enum):
    DISCLOSURE = "disclosure"
    NEWS = "news"
    EARNINGS = "earnings"
    REPORT = "report"


class NewsChunk(Base):
    __tablename__ = "news_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source_type: Mapped[NewsSourceType] = mapped_column(
        SQLEnum(NewsSourceType, name="news_source_type", create_type=True),
        nullable=False,
        index=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # DART rcept_no, RSS guid 등 source 내부 식별자. 정정공시 체인 추적용.
    corr_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # DART 정정공시 corr_rcept_no — 원본 rcept_no를 가리킴.
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(default=0, nullable=False)
    # 한 source가 여러 chunk로 분할될 때의 순번.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # sha256(chunk_text + ticker + source_id) — UniqueConstraint의 핵심.
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)

    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # 원천 사건 시각 (공시 접수 시각, 기사 발표 시각). 백테스트 시점 필터의 기준.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 수집 시각. event_time과 분리하여 retriever가 시점 필터를 정확히 걸 수 있게 함.

    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Phase 5에서 산정. 산정 규칙은 §6.1 참조.
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("ticker", "content_hash", name="uq_news_chunk_content"),
        # JSONB는 UniqueConstraint에서 비결정적이므로 content_hash로 대체.
    )


class NewsCollectionState(Base):
    """소스별 마지막 수집 시각 추적 (증분 수집용)."""

    __tablename__ = "news_collection_state"

    source_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_cursor: Mapped[str | None] = mapped_column(String(64), nullable=True)  # DART rcept_no 등
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

**timezone-aware 강제 정합성** (CHANGELOG 2026-05-13 회귀 방지):
모든 `DateTime(timezone=True)` 컬럼에 set되는 값은 `datetime.now(UTC)` 또는 aware datetime만 허용된다 (`src/db/session.py:validate_timezone_aware`). Collector가 KST naive datetime을 다루는 경우 **`event_time`을 UTC로 변환한 후 set**.

### 2.2 Alembic 마이그레이션

`.claude/skills/alembic-migration-flow/SKILL.md` 워크플로우 그대로:

```bash
# 1. 모델 수정 후 자동 생성
PYTHONPATH=. .venv/bin/alembic revision --autogenerate \
    -m "add news_chunks and collection_state"

# 2. 생성 파일 검토 (반드시 확인)
#    - pgvector extension: op.execute("CREATE EXTENSION IF NOT EXISTS vector")  ← 가장 먼저
#    - HNSW 인덱스:
#         op.create_index('idx_news_embedding', 'news_chunks', ['embedding'],
#                         postgresql_using='hnsw',
#                         postgresql_ops={'embedding': 'vector_cosine_ops'},
#                         postgresql_with={'m': 16, 'ef_construction': 64})
#    - GIN 인덱스 (전문검색): to_tsvector('simple', title || ' ' || chunk_text)
#    - enum: 신규 enum이라 create_type=True. 후속 마이그레이션에서 재사용 시 create_type=False.
#    - chunk_metadata 기본값: server_default text("'{}'::jsonb") — Alembic이 cast를 누락할 수 있음.

# 3. 적용 + 검증
PYTHONPATH=. .venv/bin/alembic upgrade head
psql "$DATABASE_URL" -c "\d news_chunks"

# 4. 롤백 검증
PYTHONPATH=. .venv/bin/alembic downgrade -1
PYTHONPATH=. .venv/bin/alembic upgrade head
```

### 2.3 Repository

파일: `src/db/repository.py`에 `NewsChunkRepository` 추가

- `insert_chunks(chunks: list[NewsChunk]) -> int` — **`ON CONFLICT (ticker, content_hash) DO NOTHING`** 패턴 사용. 배치 일부 충돌 시 나머지를 보존.
- `exists_by_hash(ticker: str, content_hash: str) -> bool` — 호출 비용 절감용 사전 체크 (선택).
- `get_collection_state(source: str) -> datetime | None`
- `update_collection_state(source: str, last_time: datetime, cursor: str | None)`

### 2.4 테스트

파일: `tests/test_db/test_news_chunk.py`, `test_news_chunk_repo.py`

- [ ] 삽입/조회
- [ ] `UniqueConstraint(ticker, content_hash)` 동작 — 동일 hash 두 번 삽입 시 ON CONFLICT
- [ ] `validate_timezone_aware` 통과 (naive datetime set 시 ValueError — 회귀 테스트)
- [ ] `Vector(1024)` 차원 검증
- [ ] `corr_source_id` 체인으로 정정공시 lookup
- [ ] `NewsCollectionState` upsert (insert + 재호출 시 update)

**완료 기준**: pytest + mypy + ruff 통과, 마이그레이션 up/down 정상, BRIDGE_SPEC 5파일 제한 준수.

---

## 3. Phase 2 — RAG 모듈 기반 구조 (2.5일)

### 3.1 디렉토리 신설

```
src/rag/
├── __init__.py
├── embedder.py          # BGE-M3 래퍼 (싱글톤)
├── chunker.py           # 청킹 전략 (source_type별)
├── ticker_matcher.py    # Aho-Corasick 기반 종목 매칭
└── sentiment.py         # 감성 점수 (선택, 후속 Phase에서 모델 결정)
```

### 3.2 Embedder

파일: `src/rag/embedder.py`

```python
class Embedder:
    """BGE-M3 싱글톤. 프로세스당 1회 로드."""

    _instance: Embedder | None = None

    def __init__(self) -> None:
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(settings.news.embedding_model, use_fp16=True)

    @classmethod
    def get(cls) -> "Embedder": ...

    def encode(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """1024-dim dense vector 반환. shape=(N, 1024)."""
```

**주의사항**

- **Worker 프로세스에서만 로드** (메인 매매 프로세스 메모리 절약). 메인은 import만 하고 인스턴스 생성 금지.
- 첫 호출 시 ~5초 워밍업 (헬스체크 ready 시그널은 워밍업 종료 후 set).
- 배치 사이즈는 메모리에 따라 조정 (M4 Pro 48GB는 12, 64GB는 32 가능).
- BGE-M3는 dense + sparse + multi-vector를 동시에 지원하지만, **초기 구현은 dense만**. sparse hybrid는 후속 retriever 단계에서.

### 3.3 Chunker

파일: `src/rag/chunker.py`

source_type별로 다른 청킹 전략:

| 타입 | 전략 |
| :---- | :---- |
| DISCLOSURE | DART XBRL 항목별 분리 (제목, 거래상대방, 거래금액, 사유) |
| NEWS | 제목 + 리드(첫 2문단). 본문은 별도 청크 |
| EARNINGS | 사업부문별 + 가이던스 섹션 |
| REPORT | 투자의견 변경 부분 + 핵심 코멘트 |

```python
class Chunker(Protocol):
    def chunk(self, raw: RawDocument) -> list[Chunk]: ...
```

각 chunk는 `chunk_index` 순번을 갖고, `content_hash = sha256(text + ticker + source_id + str(chunk_index))`로 unique.
**토큰 가드**: 모든 청커는 chunk마다 `len(text) <= NEWS_EMBEDDING_MAX_TOKENS * 4` (대략 byte 추정) 이하로 분할. 초과 시 슬라이딩 윈도우(겹침 20%)로 재분할.

### 3.4 TickerMatcher

파일: `src/rag/ticker_matcher.py`

```python
class TickerMatcher:
    """종목명 + 종목코드 정규식만으로는 false positive 폭증.
    Aho-Corasick automaton으로 다중 매칭 + 동음이의 종목 disambiguation.
    """

    def __init__(self, stocks: list[Stock]) -> None: ...

    def match(self, text: str) -> list[str]:
        """본문에서 매칭된 종목코드 리스트 반환. 빈 리스트면 ticker='MARKET'."""
```

- 종목명 사전을 `Stock` 테이블에서 부팅 시 1회 로드 (수정 시 worker 재시작).
- "삼성", "한화" 등 동음이의는 코드 풀네임("삼성전자", "한화솔루션") 우선, 단일토큰("삼성"만)은 무시.

### 3.5 테스트

파일: `tests/test_rag/`

- [ ] Embedder 출력 차원 (1024), shape 검증
- [ ] Embedder 결정론적 (같은 입력 → 같은 출력) — **실제 모델 mock**
- [ ] Chunker 각 source_type별 정상 동작
- [ ] Chunker 토큰 가드 (긴 입력 분할, 빈 입력 가드)
- [ ] TickerMatcher 정확도 — 종목명/종목코드 혼재, 동음이의, 시장전반("MARKET") 케이스

**완료 기준**: 단위 테스트 통과. 실제 BGE-M3 로딩은 별도 통합 테스트에서만 (`tests/integration/`).

---

## 4. Phase 3 — Collector 구현 (5일)

### 4.1 디렉토리

```
src/worker/collectors/
├── __init__.py
├── base.py              # BaseCollector 추상 클래스
├── dart.py              # DART OpenAPI
├── rss.py               # 연합, 이데일리 RSS
└── naver_finance.py     # 네이버 금융 (선택, 후속)
```

### 4.2 BaseCollector

```python
class BaseCollector(ABC):
    source_name: str

    @abstractmethod
    async def collect(self, since: datetime) -> list[RawDocument]:
        """since 이후의 신규 문서를 반환."""

    async def run_cycle(self) -> CollectionResult:
        """1) state 조회 → 2) collect → 3) chunk → 4) ticker_match
           → 5) embed → 6) DB 저장(ON CONFLICT) → 7) state 갱신"""
```

`RawDocument`는 `event_time`(timezone-aware), `source_id`, `corr_source_id`(선택), `raw_text`, `metadata`를 갖는 dataclass.

### 4.3 DARTCollector (최우선)

파일: `src/worker/collectors/dart.py`

**기능**:

- 공시 목록 조회: `/api/list.json` (`bgn_de`, `end_de`, `corp_code`)
- 본문 조회: `/api/document.xml` (목록과 **별도 호출** — rate-limit 계산 시 2배 가중)
- `corp_code.xml` 캐싱 (1.1 단계에서 다운로드한 파일 사용)
- 정정공시 추적: 목록 응답의 `corr_rcept_no` 필드를 그대로 `corr_source_id`에 매핑

**Rate Limit 정정**: DART는 **분당 1,000건 / 일 20,000건** (개발자 키 기준). 분당 호출이 압박이 아니라 일 한도가 압박.
관심 종목 + 추적 종목(스크리닝 상위 N)으로 corp_code를 제한해 일 한도를 통제.
구현 시 `src/api/rate_limiter.py`의 RateLimiter 패턴을 재사용 (Token Bucket).

```python
class DARTCollector(BaseCollector):
    source_name = "dart"

    async def collect(self, since: datetime) -> list[RawDocument]:
        # 1. 관심 종목 + 추적 종목 corp_code 목록 로드
        # 2. since~now 범위로 공시 목록 조회 (페이지네이션)
        # 3. 각 공시 본문 fetch (rate-limited, 본문 호출은 별도 카운트)
        # 4. 중요 공시 종류 필터 (정기공시·주요사항·지분공시·실적공시)
```

### 4.4 RSSCollector

파일: `src/worker/collectors/rss.py`

**소스 후보**:

- 연합인포맥스 RSS
- 이데일리 종목뉴스 RSS
- 한경 마켓인사이트 RSS

**필수 매너**: `User-Agent` 명시, `robots.txt` 준수, 분당 호출 제한(소스당 최대 6req/min).
종목 매핑은 `TickerMatcher` 사용. 매칭 안 되는 뉴스는 `ticker='MARKET'`.

### 4.5 NewsCollectorWorker (메인)

파일: `src/worker/news_collector.py`

```python
class NewsCollectorWorker:
    def __init__(self, collectors: list[BaseCollector]): ...

    async def run(self) -> None:
        """무한 루프 — 각 collector를 자기 주기로 실행."""
```

기존 `src/worker/runner.py`(task_queue 폴링)와 **별도 프로세스**로 띄움. 사유:

- 임베딩 모델이 메모리 ~2GB 차지
- 실패 격리 (뉴스 수집이 죽어도 매매·task_queue 처리는 계속)
- 재시작 비용 격리

**IPC는 DB 공유만**. 매매 엔진은 `news_chunks`를 read-only로 조회. NewsCollectorWorker는 read/write 모두 한다.

### 4.6 main 엔트리포인트

파일: `news_worker_main.py` (신규, 프로젝트 루트)

기존 `main.py`와 동일한 `.env` 로딩 패턴(`src/config.py:settings`)을 따른다.
구조화 로깅은 `setup_logger(__name__)` 재사용.

launchd plist 추가 (`~/Library/LaunchAgents/com.kis.news-collector.plist`):

```xml
<key>Label</key>
<string>com.kis.news-collector</string>
<key>ProgramArguments</key>
<array>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python</string>
    <string>/Users/songhansu/IdeaProjects/kis-autotrader/news_worker_main.py</string>
</array>
<key>WorkingDirectory</key>
<string>/Users/songhansu/IdeaProjects/kis-autotrader</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<!-- StandardOutPath / StandardErrorPath 는 logs/news_collector.{out,err}.log -->
```

> plist 등록은 BRIDGE_SPEC 금지 영역. **수동 PR 또는 사용자 직접 등록**.

### 4.7 테스트

파일: `tests/test_worker/test_collectors/`

- [ ] DART API mock (respx) — 응답 파싱, `corr_rcept_no` 체인
- [ ] DART 본문 호출 rate-limit (목록 + 본문이 별도 호출로 카운트)
- [ ] RSS 파싱 — 정상/깨진 XML, User-Agent 헤더 확인
- [ ] TickerMatcher 정확도 (Phase 2 테스트와 별도, 통합 시나리오)
- [ ] 증분 수집 (`NewsCollectionState` 기반 since)
- [ ] 중복 방지 (`ON CONFLICT DO NOTHING`)
- [ ] Circuit Breaker 동작 (KIS API와 동일 패턴 재사용 검증)

**완료 기준**: 모든 테스트 통과 + 1시간 실제 수집 후 DB 상태 확인 (관심 종목 5개로 좁혀서 일 한도 안전).

---

## 5. Phase 4 — 스케줄러 통합 (1일)

### 5.1 APScheduler Job 추가

파일: `src/scheduler/jobs.py`

```python
# 장중 뉴스 — 5분 간격
scheduler.add_job(
    collect_realtime_news_job,
    'cron',
    day_of_week='mon-fri',
    hour='9-15',
    minute='*/5',
    misfire_grace_time=60,
    max_instances=1,
    id='collect_realtime_news',
)

# 공시 — 개장 전·장 마감 후에 집중 발생. 07/13/18/22시.
scheduler.add_job(
    collect_disclosures_job,
    'cron',
    hour='7,13,18,22',
    misfire_grace_time=300,
    max_instances=1,
    id='collect_disclosures',
)

# 일일 클린업 — 보관 기간 경과 chunk 삭제
scheduler.add_job(
    cleanup_old_chunks_job,
    'cron',
    hour=2,
    misfire_grace_time=3600,
    id='cleanup_news_chunks',
)

# 주간 HNSW VACUUM — 대량 DELETE 후 인덱스 fragmentation 회복
scheduler.add_job(
    vacuum_news_chunks_job,
    'cron',
    day_of_week='sun', hour=3,
    id='vacuum_news_chunks',
)
```

### 5.2 휴장일 처리

기존 `src/scheduler/holidays.py` 재활용.
**휴장일이라도 공시 수집은 돌린다** — 정정공시·장후공시가 발생하므로. 뉴스 RSS도 동일.
스킵하는 것은 **장중 5분 간격 잡(`collect_realtime_news_job`)의 9~15시 부분뿐**.

### 5.3 헬스체크 통합

파일: `src/api/health.py`

`/health` 응답에 추가:

```json
{
  "news_collector": {
    "last_dart_collected_at": "2026-05-19T15:25:00+09:00",
    "last_rss_collected_at": "2026-05-19T15:30:00+09:00",
    "chunks_last_24h": 142,
    "embedding_p95_ms": 280,
    "embedder_ready": true
  }
}
```

- `embedding_p95_ms`는 `SystemMetric`의 최근 24h 윈도우 쿼리로 계산 (별도 카운터 없음).
- `embedder_ready`는 BGE-M3 워밍업 종료 후 true.

### 5.4 테스트

파일: `tests/test_scheduler/test_news_jobs.py`

- [ ] Job 등록 확인 (`id` 별로 4개)
- [ ] 휴장일 스킵 — 장중 잡만 스킵, 공시 잡은 실행
- [ ] misfire 동작

---

## 6. Phase 5 — 모니터링 및 분석 쿼리 (2일)

### 6.1 SystemMetric 기록

각 collector가 사이클 종료 시:

- `NEWS_COLLECTED` — `source`, `count`, `latency_ms`
- `NEWS_EMBEDDING_LATENCY` — 사이클당 평균. p95는 analytics 쿼리가 윈도우 백분위로 계산.
- `NEWS_DUPLICATE_RATE` — `collected` vs `new_inserted`

**Importance 산정 규칙** (Phase 5 정의):

- `DISCLOSURE`: 카테고리별 가중치 표 (`주요사항=1.0`, `정기공시=0.6`, `지분공시=0.4`, ...).
- `NEWS`: 제목 길이·종목 매칭 강도·소스 신뢰도 가중 합. (단순한 1차 휴리스틱부터 시작, 학습은 후속.)
- `EARNINGS`: 가이던스 변경 여부에 1.0, 단순 발표는 0.5.

**Sentiment 산정**: 본 Phase에서는 NULL 허용. 모델 도입(FinBERT-ko 등)은 별도 계획.

### 6.2 analytics 쿼리 추가

파일: `src/db/analytics.py`

```python
def get_news_quality_stats(date: date) -> NewsQualityStats:
    """일별 source_type별 수집 건수, 평균 importance, 임베딩 latency p50/p95."""

def get_news_coverage_by_ticker(days: int) -> list[TickerCoverage]:
    """종목별 최근 N일 뉴스 chunk 수."""
```

### 6.3 `query_analytics.py` CLI 확장

```bash
python scripts/query_analytics.py news_quality 2026-05-19
python scripts/query_analytics.py news_coverage --days 7
```

JSON 출력 포맷은 `docs/BRIDGE_SPEC.md` §"분석 쿼리 출력 포맷" 섹션에 추가 → Cowork가 일일/주간 리포트에서 파싱.

### 6.4 Telegram Bot 명령어

`src/notify/bot.py`의 `register()` 패턴으로 추가, `cmd_help` 하드코딩도 함께 갱신(CHANGELOG 2026-05-17 회귀 방지):

- `/news_stats` — 오늘 수집 현황 한 줄 요약
- `/news_coverage [종목코드]` — 특정 종목 뉴스 chunk 수

---

## 7. Phase 6 — Cowork 분석 통합 (1일, 선택)

### 7.1 일일 리포트 확장

`docs/prompts/daily_routine.md`에 다음 섹션 추가:

```markdown
## 뉴스 수집 현황
- DART 공시 수집: N건
- RSS 뉴스 수집: N건
- 임베딩 latency p95: Nms
- 실패 사이클: N건
```

### 7.2 BRIDGE_SPEC 파라미터 범위 추가

새 환경변수를 자동 파이프라인이 튜닝할 수 있도록 BRIDGE_SPEC 표에 추가:

| 파라미터 | 기본 | 범위 |
| :---- | :---- | :---- |
| `NEWS_COLLECT_INTERVAL_MIN` | 5 | 3 ~ 15 |
| `NEWS_DART_RATE_LIMIT_PER_SEC` | 1.0 | 0.5 ~ 2.0 |
| `NEWS_EMBEDDING_BATCH_SIZE` | 12 | 4 ~ 32 |
| `NEWS_CHUNK_RETENTION_DAYS` | 90 | 30 ~ 365 |
| `NEWS_DISCLOSURE_WEIGHT` | 1.0 | 0.5 ~ 2.0 |
| `NEWS_RSS_WEIGHT` | 0.6 | 0.3 ~ 1.5 |

---

## 8. 일정 요약

| Phase | 기간 | 산출물 |
| :---- | :---- | :---- |
| 0. 사전 준비 | 1일 | DART 키, 의존성 PR, docker-compose pgvector 교체, BGE-M3 사전 다운로드 |
| 1. DB 스키마 | 2일 | `news_chunks` 테이블, Repository, 테스트 (1a/1b 분할) |
| 2. RAG 모듈 | 2.5일 | Embedder, Chunker, TickerMatcher |
| 3. Collectors | 5일 | DART, RSS, Worker, launchd plist |
| 4. 스케줄러 | 1일 | APScheduler 통합, HNSW VACUUM 잡 |
| 5. 모니터링 | 2일 | analytics, 헬스체크, Telegram, importance 산정 |
| 6. Cowork 통합 | 1일 | 리포트 prompt, BRIDGE_SPEC 갱신 |
| **합계** | **~14.5일** | (실가동, calendar로는 3~4주) |

> 원안 11.5일은 정정공시 체인, 종목 매칭 정확도, BGE-M3 운영(launchd 환경 권한), BRIDGE_SPEC 5파일 분할 PR 비용을 빠뜨림. 보정 후 14.5일.

---

## 9. 리스크 및 대응

| 리스크 | 대응 |
| :---- | :---- |
| BGE-M3 메모리 초과 | use_fp16=True, batch_size 축소. 최후엔 Q8 양자화 버전(~600MB) |
| BGE-M3 첫 로드 권한/네트워크 실패 (launchd 환경) | 사전 다운로드 후 `~/.cache/huggingface/` 권한 사용자 보유 확인 |
| DART API 일 한도 초과 | 관심 + 추적 종목으로 corp_code 제한, 목록·본문 별도 카운팅 |
| RSS 사이트 차단 | User-Agent 명시, 분당 호출 제한, robots.txt 준수, 백오프 |
| 정정공시 누락 | `corr_rcept_no` → `corr_source_id` 체인 추적, 정기 재검증 잡 |
| 종목 매칭 정확도 낮음 (false positive) | Aho-Corasick + 동음이의 disambiguation 룰 + 종목 사전 보강 |
| pgvector 인덱스 성능 저하 | HNSW `m=16, ef_construction=64` 튜닝, 주간 VACUUM 잡 |
| 임베딩 latency 누적 | 비동기 큐 + 배치 임베딩, `embedding_p95_ms` 헬스체크 모니터 |
| 시간대 버그 재발 (CHANGELOG 2026-05-13) | `validate_timezone_aware` 회귀 테스트 유지, KST→UTC 변환 단위 테스트 |
| LLM 동시 구동 시 메모리 압박 | 32B는 온디맨드 로딩, 상시 hot은 7B/14B |
| JSONB unique 부적합 (원안 버그) | `content_hash` 컬럼으로 대체, `ON CONFLICT (ticker, content_hash)` |

---

## 10. 완료 정의 (Definition of Done)

이 작업이 끝났다고 말하려면 아래가 모두 통과:

- [ ] `pytest tests/test_db/test_news_chunk.py tests/test_db/test_news_chunk_repo.py tests/test_rag/ tests/test_worker/test_collectors/ tests/test_scheduler/test_news_jobs.py` 100% pass
- [ ] `python -m mypy src/rag/ src/worker/collectors/ src/worker/news_collector.py` strict 통과
- [ ] `ruff check src/rag/ src/worker/collectors/ src/worker/news_collector.py` 통과
- [ ] Alembic upgrade/downgrade 양방향 정상
- [ ] 1시간 연속 수집 → DB에 chunk 100건 이상 적재, `ON CONFLICT` 동작 확인
- [ ] `/health` 응답에 `news_collector` 상태 노출, `embedder_ready=true`
- [ ] `python scripts/query_analytics.py news_quality $(date +%Y-%m-%d)` 정상 JSON 출력
- [ ] launchd `com.kis.news-collector` 백그라운드 실행 + 재시작 검증
- [ ] CHANGELOG.md rolling 갱신 (Phase별 5파일 제한 준수로 PR 다수) + `scripts/record_implementation.py` 기록 (DB)

---

## 11. 후속 작업 (이 계획 이후)

다음 단계는 별도 계획서로 분리:

1. **검색 모듈** (`src/rag/retriever.py`) — 하이브리드 검색(dense + BM25) + 시간 가중 + **백테스트 look-ahead 차단(`event_time <= as_of_time` 필터)**
2. **LLM 클라이언트** (`src/rag/llm_client.py`) — Ollama 연동
3. **매매 엔진 통합** (`src/engine.py` 확장) — 2단계 추론 흐름
4. **Sentiment 모델 도입** — FinBERT-ko 또는 KoBERT 파인튜닝 평가
5. **추가 데이터 소스** — 한경컨센서스 리포트, 종목토론실 감성

---

## 12. 하드웨어 자원 계획 (참고, §1.5 통합)

### 대상 환경: M4 Pro 48GB Mac Mini

| 컴포넌트 | 메모리 | 비고 |
| :---- | :---- | :---- |
| macOS 시스템 | 6GB |  |
| PostgreSQL 16 (pgvector) | 2~3GB | shared_buffers 1GB. HNSW 인덱스 메모리는 별도 |
| 매매엔진 (`main.py`) | 0.5~1GB |  |
| Worker (`runner.py`, task_queue) | 0.3GB |  |
| **NewsCollectorWorker** | **3~4GB** | BGE-M3 포함 |
| Streamlit (간헐적) | 0.5GB |  |
| 자동구현 하네스 (간헐적) | 2~3GB | pytest + mypy 병렬 |
| **소계 (LLM 제외 상시)** | **~13GB** |  |
| Qwen2.5-7B Q4 (상시 hot, 1차 필터) | 5GB | 50~80 tok/s |
| Qwen2.5-32B Q4 (온디맨드, 심층 분석) | ~24GB | 12~18 tok/s |
| LLM KV cache (8K~16K) | 2~4GB |  |
| 여유 | ~5GB | macOS 메모리 압박 방지 |

### 운영 시나리오

**평상시 (LLM idle)**
- 13GB + 7B hot 5GB = 18GB 사용. 마진 30GB.

**시그널 발생 → 32B 호출 시**
- 13GB + 7B 5GB + 32B 24GB + KV 3GB = 45GB. 마진 3GB. ⚠️ 빡빡.
- 대응: 32B 추론 종료 후 메모리 해제 또는 7B unload.

**자동구현 하네스 + 32B 동시**
- 17:00 cron + 동시 시그널 (가능성 낮음)
- 45GB + 3GB = 48GB 초과 가능 → swap 위험
- 대응: 자동구현 시간대에는 LLM idle 모드로 전환

**추천 정책**

1. 7B를 상시 hot으로 두고 거의 모든 시그널을 1차 필터링
2. 1차 통과 시 32B를 lazy load (첫 호출 시 5~10초 지연 감수)
3. 32B는 마지막 사용 후 5분 idle 시 unload
4. 자동구현 cron 시작 시 LLM 강제 unload, 종료 후 재로드

이 정책이면 48GB 안에서 안정적 운영 가능.
