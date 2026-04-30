# 시스템 아키텍처 다이어그램 (Mermaid)

## 옵션 A: 전체 시스템 흐름도 (Flowchart)

Mermaid Live Editor (https://mermaid.live) 에 붙여넣으면 바로 렌더링됩니다.
Slidev에서는 코드블록 안에 `mermaid`로 감싸면 자동 렌더링됩니다.

```mermaid
flowchart TB
    subgraph MAC["Macbook (launchd, 24/7)"]
        direction TB

        subgraph ENGINE["Trading Engine"]
            direction LR
            PRE["08:30<br/>pre_market<br/>토큰 갱신·관심종목"]
            TRADE["09:00~15:20<br/>trading<br/>시세→전략→리스크→주문"]
            POST["15:40<br/>post_market<br/>결산·Calendar 큐잉"]
            SUMMARY["16:00<br/>summarize<br/>daily_summary UPSERT"]
            PRE --> TRADE --> POST --> SUMMARY
        end

        subgraph SAFETY["안전장치 레이어"]
            RL["3중 Rate Limiter<br/>Token Bucket"]
            CB["Circuit Breaker<br/>5회 실패→서킷 열림"]
            WS["WebSocket<br/>상태머신"]
        end

        subgraph DATA["데이터 레이어"]
            PG[("PostgreSQL 16<br/>trades·signals·screening<br/>daily_perf·daily_summary<br/>impl_logs·system_metrics")]
            REDIS[("Redis 7<br/>Rate Limit<br/>Worker 큐")]
        end

        subgraph WORKERS["Workers (Outbox 패턴)"]
            CW["Calendar Worker<br/>Google Calendar API"]
            TW["Telegram Worker<br/>Bot API"]
            DW["DB Worker<br/>Trade·Signal·Metric<br/>Performance·Summary·Portfolio"]
            SW["Screening Worker<br/>별도 API 할당량"]
        end

        subgraph AUTOPIPE["자율 개선 루프"]
            direction LR
            COWORK["16:00 Cowork<br/>분석·제안서 작성"]
            PROPOSALS["docs/proposals/*.md<br/>state: ready"]
            CLAUDE["17:00 Claude Code<br/>안전 게이트 검증"]
            IMPL["코드 수정<br/>pytest·mypy·ruff"]
            RESTART["서비스 재시작<br/>launchctl restart"]
            FAIL["git restore<br/>state: failed"]

            COWORK -->|"리포트+제안서"| PROPOSALS
            PROPOSALS -->|"ready 수집"| CLAUDE
            CLAUDE -->|"통과"| IMPL
            CLAUDE -->|"위반"| FAIL
            IMPL -->|"pass"| RESTART
            IMPL -->|"fail"| FAIL
        end

        subgraph AUTOHEAL["자동 진단/복구"]
            WD["watchdog.sh<br/>프로세스·헬스체크 감시<br/>5분 간격 (launchd)"]
            AH["auto_heal.sh<br/>Claude Code 진단·수정"]
            WD -->|"3회 이상<br/>재시작 감지"| AH
            AH -->|"수정·재시작"| ENGINE
        end

        subgraph MONITOR["모니터링"]
            HEALTH["Health Check<br/>/health :18923"]
            DASH["Streamlit<br/>대시보드 :8501<br/>(launchd)"]
        end

        subgraph INFRA["인프라 (launchd)"]
            BACKUP["backup_db.sh<br/>pg_dump + gzip<br/>7일 롤링"]
        end

        ENGINE --> SAFETY
        SAFETY --> DATA
        DATA --> WORKERS
        DATA --> AUTOPIPE
        ENGINE --> MONITOR
        DATA --> INFRA
    end

    TGBOT["Telegram Bot<br/>16종 명령어"]
    GCAL["Google Calendar"]
    KISAPI["KIS OpenAPI<br/>한국투자증권"]

    TGBOT <-->|"원격 조작"| TW
    CW -->|"이벤트 등록"| GCAL
    KISAPI <-->|"시세·주문"| ENGINE

    style ENGINE fill:#1a1a2e,stroke:#0f3460,color:#e0e0e0
    style AUTOPIPE fill:#0a1628,stroke:#16c79a,color:#e0e0e0
    style SAFETY fill:#1a1a2e,stroke:#e94560,color:#e0e0e0
    style AUTOHEAL fill:#1a1a2e,stroke:#f39c12,color:#e0e0e0
    style DATA fill:#1a1a2e,stroke:#3282b8,color:#e0e0e0
    style MAC fill:#0d0d1a,stroke:#444,color:#e0e0e0
```

---

## 옵션 B: 자율 개선 루프 시퀀스 다이어그램

```mermaid
sequenceDiagram
    participant CRON as Scheduler (launchd)
    participant CW as Cowork (분석 AI)
    participant FS as docs/proposals/
    participant CC as Claude Code (구현 AI)
    participant GATE as Safety Gate
    participant CODE as Codebase
    participant TEST as pytest·mypy·ruff
    participant SVC as autotrader Service
    participant DB as PostgreSQL

    Note over CRON: 평일 16:00
    CRON->>CW: 일일 분석 트리거
    CW->>DB: query_analytics.py (거래·시그널·리스크 JSON)
    DB-->>CW: 구조화된 분석 데이터
    CW->>FS: 제안서 작성 (state: ready)
    CW->>FS: 일일 리포트 생성

    Note over CRON: 평일 17:00
    CRON->>CC: 자동 구현 트리거
    CC->>FS: ready 제안서 수집
    CC->>GATE: 안전 게이트 검증

    alt 게이트 통과
        GATE-->>CC: PASS
        CC->>CODE: 코드 수정
        CC->>TEST: 검증 실행
        alt 테스트 통과
            TEST-->>CC: ALL PASS
            CC->>FS: state → implemented
            CC->>DB: implementation_logs 기록
            CC->>SVC: launchctl restart
        else 테스트 실패
            TEST-->>CC: FAIL
            CC->>CODE: git restore (원복)
            CC->>FS: state → failed
        end
    else 게이트 위반
        GATE-->>CC: REJECT (금지 영역/범위 초과)
        CC->>FS: state → skipped
    end

    Note over CRON: 금요일 16:30
    CRON->>CW: 주간 리뷰 트리거
    CW->>DB: 주간 데이터 분석
    CW->>FS: 주간 리포트 + 중기 제안서
```

---

## 옵션 C: C4 Model 스타일 (컨테이너 다이어그램)

```mermaid
C4Container
    title KIS AutoTrader - 컨테이너 다이어그램

    Person(dev, "개발자", "CHANGELOG·리포트 검토<br/>시스템 설계·의사결정")

    System_Boundary(mac, "Macbook (launchd, 24/7)") {
        Container(engine, "Trading Engine", "Python/APScheduler", "시세조회·전략실행·리스크관리·주문")
        Container(workers, "Workers", "Python/Redis", "Calendar·Telegram·Screening<br/>Outbox 패턴")
        Container(cowork, "Cowork", "Claude AI", "데이터 분석·제안서 작성<br/>평일 16:00")
        Container(claude, "Claude Code", "Claude AI", "안전 게이트·코드 구현<br/>평일 17:00")
        Container(watchdog, "Watchdog", "Bash/launchd", "프로세스 감시·자동 복구<br/>auto_heal 파이프라인")
        Container(dashboard, "Dashboard", "Streamlit", "매매·성과·리스크 시각화")
        ContainerDb(pg, "PostgreSQL 16", "SQL", "trades·signals·screening<br/>daily_perf·daily_summary<br/>impl_logs·system_metrics")
        ContainerDb(redis, "Redis 7", "K/V", "Rate Limit·Worker Queue")
        Container(docs, "docs/", "Markdown", "proposals·reports<br/>BRIDGE_SPEC·CHANGELOG")
    }

    System_Ext(kis, "KIS OpenAPI", "한국투자증권 시세·주문 API")
    System_Ext(gcal, "Google Calendar", "매매 결과 이벤트 등록")
    System_Ext(tg, "Telegram Bot", "알림·16종 원격 명령")

    Rel(dev, docs, "리포트·CHANGELOG 검토")
    Rel(engine, kis, "REST/WebSocket")
    Rel(engine, pg, "거래·시그널 저장")
    Rel(engine, redis, "Rate Limit 체크")
    Rel(workers, gcal, "이벤트 등록")
    Rel(workers, tg, "알림 전송")
    Rel(workers, pg, "Outbox 폴링")
    Rel(cowork, pg, "분석 쿼리")
    Rel(cowork, docs, "제안서·리포트 작성")
    Rel(claude, docs, "제안서 수집·상태 갱신")
    Rel(claude, engine, "코드 수정·서비스 재시작")
    Rel(watchdog, engine, "프로세스 감시·재시작")
    Rel(dashboard, pg, "데이터 조회")
```
