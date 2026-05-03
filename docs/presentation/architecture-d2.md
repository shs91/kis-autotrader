# 시스템 아키텍처 다이어그램 (D2)

D2는 최근 인기있는 다이어그램 언어입니다. https://d2lang.com 또는 https://play.d2lang.com 에서 렌더링 가능합니다.

## 옵션 D: D2 다이어그램

```d2
direction: down

mac: Macbook (launchd, 24/7) {
  style: {
    fill: "#0d0d1a"
    stroke: "#444"
    font-color: "#e0e0e0"
  }

  engine: Trading Engine {
    style: {
      fill: "#1a1a2e"
      stroke: "#0f3460"
      font-color: "#e0e0e0"
    }
    pre: "08:30 pre_market\n토큰 갱신, 관심종목"
    trade: "09:00~15:30 trading\n시세→전략→리스크→주문"
    post: "15:40 post_market\n결산, Calendar 큐잉"
    summary: "16:00 summarize\ndaily_summary UPSERT"

    pre -> trade -> post -> summary
  }

  safety: 안전장치 레이어 {
    style: {
      fill: "#1a1a2e"
      stroke: "#e94560"
    }
    rl: "3중 Rate Limiter\nToken Bucket"
    cb: "Circuit Breaker\n5회 실패→서킷 열림"
    ws: "WebSocket 상태머신\nDISCONNECTED→ACTIVE"
  }

  data: 데이터 레이어 {
    style: {
      fill: "#1a1a2e"
      stroke: "#3282b8"
    }
    pg: PostgreSQL 16 {
      shape: cylinder
      label: "PostgreSQL 16\ntrades · signals · screening\nperf · impl_logs"
    }
    redis: Redis 7 {
      shape: cylinder
      label: "Redis 7\nRate Limit · Worker Queue"
    }
  }

  workers: Workers (Outbox 패턴) {
    style: {
      fill: "#1a1a2e"
      stroke: "#9b59b6"
    }
    calendar: "Calendar Worker\nGoogle Calendar API"
    telegram: "Telegram Worker\nBot API (16종 명령)"
    screening: "Screening Worker\n별도 API 할당량"
  }

  autopipe: 자율 개선 루프 {
    style: {
      fill: "#0a1628"
      stroke: "#16c79a"
      font-color: "#16c79a"
    }

    cowork: "16:00 Cowork\n(분석 AI)" {
      style.fill: "#0a2e1a"
    }
    proposals: "docs/proposals/*.md\nstate: ready" {
      shape: document
    }
    claude: "17:00 Claude Code\n(구현 AI)" {
      style.fill: "#2e1a0a"
    }
    gate: "Safety Gate\n금지영역 · 파라미터범위\n코드변경규칙" {
      shape: hexagon
      style.fill: "#2e0a0a"
    }
    impl: "코드 수정\npytest · mypy · ruff" {
      style.fill: "#0a1a2e"
    }
    restart: "서비스 재시작\nlaunchctl restart" {
      style.fill: "#0a2e1a"
    }
    fail: "git restore\nstate: failed" {
      style.fill: "#2e0a0a"
    }

    cowork -> proposals: "리포트 + 제안서"
    proposals -> claude: "ready 수집"
    claude -> gate: "검증 요청"
    gate -> impl: "통과" {style.stroke: "#16c79a"}
    gate -> fail: "위반" {style.stroke: "#e94560"}
    impl -> restart: "pass" {style.stroke: "#16c79a"}
    impl -> fail: "fail" {style.stroke: "#e94560"}
  }

  autoheal: 자동 진단/복구 {
    style: {
      fill: "#1a1a2e"
      stroke: "#f39c12"
    }
    watchdog: "watchdog.sh\n프로세스 감시\n주말/공휴일 인식"
    heal: "auto_heal.sh\n자동 진단 · 복구"
    watchdog -> heal: "이상 감지"
  }

  monitor: 모니터링 {
    style.fill: "#1a1a2e"
    health: "Health Check\n/health :18923"
    dash: "Streamlit 대시보드\n:8501"
  }

  engine -> safety
  safety -> data
  data -> workers
  autoheal.heal -> engine: "재시작"
  data.pg -> autopipe.cowork: "분석 쿼리"
}

kis: KIS OpenAPI {
  shape: cloud
  label: "KIS OpenAPI\n한국투자증권"
}
gcal: Google Calendar {
  shape: cloud
}
tg: Telegram Bot {
  shape: cloud
  label: "Telegram Bot\n16종 원격 명령"
}

kis <-> mac.engine: "REST / WebSocket"
mac.workers.calendar -> gcal: "이벤트 등록"
tg <-> mac.workers.telegram: "알림 · 원격 조작"
```
