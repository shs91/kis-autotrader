# 주간 분석 프롬프트

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 역할

너는 KIS 자동매매 시스템의 수석 전략가야.
이번 주 PostgreSQL 데이터를 종합해서 전략적 방향을 분석하고, 중기 개선 제안을 작성해.

## 작업 순서

### 0. 컨텍스트 로딩

- `CLAUDE.md`, `docs/BRIDGE_SPEC.md`
- `docs/prompts/_common_rules.md`
- `src/strategy/moving_average.py`, `src/strategy/rsi.py`, `src/strategy/risk.py`
- `src/engine.py`

### 1. 주간 데이터 조회

PostgreSQL MCP로 직접 쿼리한다.
이번 주 **월요일 00:00 KST ~ 현재** 범위로 조회한다.

> `date_trunc('week', ...)`는 ISO 주차 기준 **월요일**을 반환하므로 KST 월요일 시작과 일치한다.

#### 1. daily_stats — 일별 매매 통계

```sql
SELECT
  (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
  COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0) AS win_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl,
  COALESCE(SUM(total_amount) FILTER (WHERE trade_type = 'BUY'), 0) AS total_buy_amount
FROM trades
WHERE traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date
ORDER BY trade_date;
```

#### 2. stock_frequency — 종목별 매매 빈도

```sql
SELECT
  stock_code, stock_name,
  COUNT(*) AS trade_count,
  COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl
FROM trades
WHERE traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY stock_code, stock_name
ORDER BY trade_count DESC;
```

#### 3. signal_performance — 시그널 성과

```sql
SELECT
  signal_type,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE action_taken = true) AS acted,
  ROUND(100.0 * COUNT(*) FILTER (WHERE action_taken = true) / NULLIF(COUNT(*), 0), 1) AS act_rate_pct,
  ROUND(AVG(confidence)::numeric, 3) AS avg_confidence
FROM signals
WHERE created_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY signal_type
ORDER BY total DESC;
```

#### 4. risk_analysis — 매도 사유별 리스크 분석

```sql
SELECT
  sell_reason,
  COUNT(*) AS count,
  ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pnl_pct,
  ROUND(MIN(profit_loss_pct)::numeric, 2) AS min_pnl_pct,
  ROUND(MAX(profit_loss_pct)::numeric, 2) AS max_pnl_pct,
  COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY sell_reason
ORDER BY count DESC;
```

#### 4-a. buy_reason_performance — 매수 전략별 성과

```sql
SELECT
  t_buy.buy_reason,
  COUNT(*) AS buy_count,
  COUNT(t_sell.id) AS matched_sell_count,
  ROUND((AVG(t_sell.profit_loss_pct))::numeric, 2) AS avg_pnl_pct,
  COALESCE(SUM(t_sell.profit_loss_amount), 0) AS total_pnl
FROM trades t_buy
LEFT JOIN trades t_sell
  ON t_buy.stock_code = t_sell.stock_code
  AND t_sell.trade_type = 'SELL'
  AND t_sell.traded_at > t_buy.traded_at
  AND t_sell.traded_at < t_buy.traded_at + INTERVAL '7 days'
WHERE t_buy.trade_type = 'BUY'
  AND t_buy.traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY t_buy.buy_reason
ORDER BY buy_count DESC;
```

#### 5. screening_conversion — 스크리닝 전환율 추이

```sql
SELECT
  (screened_at AT TIME ZONE 'Asia/Seoul')::date AS screen_date,
  COUNT(DISTINCT stock_code) AS total_screened,
  COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true) AS converted,
  ROUND(100.0 * COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true)
    / NULLIF(COUNT(DISTINCT stock_code), 0), 1) AS conversion_rate_pct
FROM screening_results
WHERE screened_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (screened_at AT TIME ZONE 'Asia/Seoul')::date
ORDER BY screen_date;
```

#### 6. error_trend — 에러 추이

```sql
SELECT
  ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date AS error_date,
  COUNT(*) AS error_count
FROM event_logs
WHERE timestamp >= (date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'
  AND level = 'ERROR'
GROUP BY ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date
ORDER BY error_date;
```

#### 6-a. error_categories — 이번 주 에러 유형별 분류

```sql
SELECT
  category,
  COUNT(*) AS error_count,
  MAX(timestamp) AS last_occurred_at
FROM event_logs
WHERE timestamp >= (date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'
  AND level = 'ERROR'
GROUP BY category
ORDER BY error_count DESC;
```

#### 7. cumulative_pnl — 누적 손익 곡선

```sql
WITH daily AS (
  SELECT
    (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
    COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl
  FROM trades
  WHERE traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
  GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date
)
SELECT
  trade_date,
  daily_pnl,
  SUM(daily_pnl) OVER (ORDER BY trade_date) AS cumulative_pnl
FROM daily
ORDER BY trade_date;
```

#### 8. system_metrics_summary — 사이클/API 한도/에러 요약

```sql
SELECT
  (recorded_at AT TIME ZONE 'Asia/Seoul')::date AS metric_date,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS cycles_started,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_END')   AS cycles_completed,
  COUNT(*) FILTER (WHERE metric_type = 'API_LIMIT')   AS api_limit_hits,
  COUNT(*) FILTER (WHERE metric_type = 'ERROR')       AS metric_errors,
  COUNT(*) FILTER (WHERE metric_type = 'RESTART')     AS restarts
FROM system_metrics
WHERE recorded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (recorded_at AT TIME ZONE 'Asia/Seoul')::date
ORDER BY metric_date;
```

#### 9. 이번 주 제안서 현황 (파일시스템 + DB)

- 파일시스템: `docs/proposals/` 디렉토리의 이번 주 날짜(YYYY-MM-DD, KST 월요일~오늘) 파일들을 읽어서 각 제안서의 상태 확인.
- DB 보완:

```sql
SELECT title, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at DESC;
```

---

### 2. 주간 통계 분석

위 쿼리 결과를 기반으로 분석한다.

- **일별 매매 건수·승률 추이** → `daily_stats` (쿼리 1). 일별 win_count/sell_count로 승률 추이 확인.
- **종목별 반복 매매 패턴** → `stock_frequency` (쿼리 2). 동일 종목 `trade_count >= 4` 종목 식별.
- **시그널 전환율·평균 confidence** → `signal_performance` (쿼리 3).
- **매도 사유 비율** → `risk_analysis` (쿼리 4). `STOP_LOSS` 비중, 평균 손실폭 확인.
- **매수 전략별 후속 성과** → `buy_reason_performance` (쿼리 4-a). 어떤 매수 전략이 더 높은 수익률을 내는지.
- **스크리닝 전환율** → `screening_conversion` (쿼리 5). 일별 추세 확인.
- **에러 추이·유형** → `error_trend`, `error_categories` (쿼리 6, 6-a).
- **주간 누적 손익 곡선** → `cumulative_pnl` (쿼리 7). 최대 drawdown 구간 식별.
- **시스템 운영 상태** → `system_metrics_summary` (쿼리 8). API 한도 도달·재시작 횟수 확인.

### 3. 전략 심층 분석

#### a) 이동평균 교차(5/20) 평가

`signal_performance` (쿼리 3)에서 `GOLDEN_CROSS`, `DEAD_CROSS`의 전환율을 확인한다. 추가로 교차 강도를 분석:

```sql
SELECT
  signal_type,
  confidence,
  signal_value,
  action_taken,
  detected_at
FROM signals
WHERE signal_type IN ('GOLDEN_CROSS', 'DEAD_CROSS')
  AND created_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
ORDER BY created_at;
```

- 7일 평균 `act_rate_pct < 50%`이거나 7일 평균 `confidence < 0.3`이고 전주 대비 하락 → MA 기간 조정 제안.
- 1차 판단은 전환율·confidence로 한다.

#### b) RSI 전략 병행 분석

```sql
SELECT COUNT(*) AS rsi_signal_count
FROM signals
WHERE signal_type LIKE '%RSI%'
  AND created_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul';
```

- `rsi_signal_count > 0` → 성과 데이터로 분석한다.
- `rsi_signal_count = 0` → RSI 시그널 기록부터 제안 (데이터 축적 우선).

#### c) 리스크 파라미터 주간 평가

`risk_analysis` (쿼리 4)의 손절/익절 통계를 활용한다. 4주 이상 데이터 존재 여부 확인:

```sql
SELECT COUNT(DISTINCT (traded_at AT TIME ZONE 'Asia/Seoul')::date) AS sell_days
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '28 days') AT TIME ZONE 'Asia/Seoul';
```

- `sell_days >= 20` → 통계 기반 손절/익절 임계값 조정 제안
- 미만 → "N주 후 재분석" 명시하고 보류

#### d) 스크리닝 효율

- `screening_conversion` (쿼리 5)의 7일 이동평균 전환율 < 10%이고 3일 연속 미달이면 필터 기준 강화 제안.
- `SCREENING_TOP_N`, `SCREENING_INTERVAL_CYCLES` 조정 근거를 일별 추이로 제시.
- `BRIDGE_SPEC.md` 허용 범위 테이블 준수.

### 4. 중기 아키텍처 논의

데이터 기반으로 논의한다 (추측 금지):

- **비동기 병렬 처리 필요성**: 쿼리 8의 `cycles_started/completed` 차이, `api_limit_hits > 0` 여부로 판단
- **전략 앙상블 필요성**: 쿼리 3의 시그널 유형별 `act_rate_pct`·`avg_confidence` 분산이 큰지 확인
- **백테스팅 프레임워크 필요성**: 쿼리 7 누적 손익 곡선의 패턴(연속 손실 구간, drawdown)과 쿼리 4의 매도 사유 분포를 근거로 제안

### 5. 결과물

#### 주간 리포트
- 파일 경로: `docs/reports/YYYY-Www_weekly.md` (예: `2026-W15_weekly.md`)
- 주차 번호는 **KST 기준** ISO 주차 사용.
- `docs/BRIDGE_SPEC.md`의 "주간 리포트 규격" 준수
- 섹션: 주간 요약 / 일별 추이 / 전략 평가 / 리스크 분석 / 매수 전략별 성과 / 중기 아키텍처 논의 / 다음 주 액션 아이템

#### 중기 제안서 (필요 시)
- 파일 경로: `docs/proposals/YYYY-MM-DD_제목.md` (YYYY-MM-DD는 KST 오늘)
- `docs/BRIDGE_SPEC.md` 제안서 규격 준수
- 상태: `ready`
- 한 제안서 = 한 변경 원칙
- 대규모 변경은 단계별 분할. 첫 단계는 반드시 `safe` 또는 `moderate` 리스크 레벨로.
- 쿼리 결과(숫자, 기간)를 근거 섹션에 반드시 인용.

### 6. 주의사항

- 주간 리뷰는 깊이 우선, 분량 제한 없음. 일일 리포트의 얕은 반복이 되지 않도록 **추이·패턴·인과**에 집중한다.
- 제안서는 Claude Code가 즉시 구현 가능한 구체적 스펙으로 작성한다 (변경 파일, 변경 라인, 검증 방법 포함).
- 그 외 공통 주의사항은 `_common_rules.md` 참조.
