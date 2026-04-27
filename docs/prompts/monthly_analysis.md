# 월간 분석 프롬프트

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 실행 조건 (최우선 확인)

아래 쿼리로 오늘이 이번 달 마지막 금요일인지 확인한다. **아니면 즉시 종료.**

```sql
SELECT
  (now() AT TIME ZONE 'Asia/Seoul')::date AS today,
  (
    -- 이번 달 마지막 날에서 요일 오프셋으로 마지막 금요일 계산
    (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day')::date
    - ((EXTRACT(DOW FROM (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day'))::int + 2) % 7)
  ) AS last_friday,
  (now() AT TIME ZONE 'Asia/Seoul')::date = (
    (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day')::date
    - ((EXTRACT(DOW FROM (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') + INTERVAL '1 month - 1 day'))::int + 2) % 7)
  ) AS is_last_friday;
```

`is_last_friday = false`이면 "월간 분석 실행 조건 미충족 (마지막 금요일 아님). 종료."만 출력하고 끝낸다.

## 역할

너는 KIS 자동매매 시스템의 CIO (Chief Investment Officer)야.
이번 달 전체 PostgreSQL 데이터를 기반으로 투자 전략의 근본적 방향을 평가해.

## 작업 순서

### 0. 컨텍스트 로딩

- `CLAUDE.md`, `docs/BRIDGE_SPEC.md`
- `docs/prompts/_common_rules.md`
- `src/strategy/moving_average.py`, `src/strategy/rsi.py`, `src/strategy/risk.py`
- `src/engine.py`

### 1. 월간 데이터 조회

PostgreSQL MCP로 직접 쿼리한다.
이번 달 **1일 00:00 KST ~ 현재** 범위로 조회한다.

#### 1. monthly_cumulative_pnl — 월간 일별 손익 및 누적 손익

```sql
WITH daily AS (
  SELECT
    (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
    COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
    COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
    COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0) AS win_count,
    COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl,
    COALESCE(SUM(total_amount) FILTER (WHERE trade_type = 'BUY'), 0) AS daily_buy_amount
  FROM trades
  WHERE traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
  GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date
)
SELECT
  trade_date,
  buy_count,
  sell_count,
  win_count,
  daily_pnl,
  daily_buy_amount,
  SUM(daily_pnl) OVER (ORDER BY trade_date) AS cumulative_pnl
FROM daily
ORDER BY trade_date;
```

#### 2. weekly_breakdown — 주차별 성과 추이 (ISO 주차, KST)

```sql
SELECT
  EXTRACT(ISOYEAR FROM traded_at AT TIME ZONE 'Asia/Seoul')::int AS iso_year,
  EXTRACT(WEEK FROM traded_at AT TIME ZONE 'Asia/Seoul')::int AS iso_week,
  MIN((traded_at AT TIME ZONE 'Asia/Seoul')::date)::text
    || ' ~ ' ||
    MAX((traded_at AT TIME ZONE 'Asia/Seoul')::date)::text AS period,
  COUNT(*) AS total_trades,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS weekly_pnl,
  ROUND((AVG(profit_loss_pct) FILTER (WHERE trade_type = 'SELL'))::numeric, 2) AS avg_pnl_pct
FROM trades
WHERE traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY iso_year, iso_week
ORDER BY iso_year, iso_week;
```

#### 3. stock_performance_top — 종목별 월간 성과 TOP 5

```sql
SELECT
  stock_code, stock_name,
  COUNT(*) AS trade_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl,
  ROUND((AVG(profit_loss_pct) FILTER (WHERE trade_type = 'SELL'))::numeric, 2) AS avg_pnl_pct
FROM trades
WHERE traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY stock_code, stock_name
HAVING COUNT(*) FILTER (WHERE trade_type = 'SELL') > 0
ORDER BY total_pnl DESC
LIMIT 5;
```

#### 4. stock_performance_bottom — 종목별 월간 성과 BOTTOM 5

```sql
SELECT
  stock_code, stock_name,
  COUNT(*) AS trade_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl,
  ROUND((AVG(profit_loss_pct) FILTER (WHERE trade_type = 'SELL'))::numeric, 2) AS avg_pnl_pct
FROM trades
WHERE traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY stock_code, stock_name
HAVING COUNT(*) FILTER (WHERE trade_type = 'SELL') > 0
ORDER BY total_pnl ASC
LIMIT 5;
```

#### 5. signal_accuracy — 시그널 유형별 월간 정확도

```sql
SELECT
  signal_type,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE action_taken = true) AS acted,
  ROUND(100.0 * COUNT(*) FILTER (WHERE action_taken = true) / NULLIF(COUNT(*), 0), 1) AS act_rate_pct,
  ROUND(AVG(confidence)::numeric, 3) AS avg_confidence,
  ROUND(MIN(confidence)::numeric, 3) AS min_confidence,
  ROUND(MAX(confidence)::numeric, 3) AS max_confidence
FROM signals
WHERE created_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY signal_type
ORDER BY total DESC;
```

#### 6. daily_win_rate — 월간 승률 추이 (일별)

```sql
SELECT
  (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS total_sells,
  COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0) AS wins,
  ROUND(100.0 * COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0)
    / NULLIF(COUNT(*) FILTER (WHERE trade_type = 'SELL'), 0), 1) AS win_rate_pct
FROM trades
WHERE traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date
HAVING COUNT(*) FILTER (WHERE trade_type = 'SELL') > 0
ORDER BY trade_date;
```

#### 7. sell_reason_stats — 매도 사유별 월간 통계 (중앙값 포함)

```sql
SELECT
  sell_reason,
  COUNT(*) AS count,
  ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pnl_pct,
  ROUND(MIN(profit_loss_pct)::numeric, 2) AS min_pnl_pct,
  ROUND(MAX(profit_loss_pct)::numeric, 2) AS max_pnl_pct,
  ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY profit_loss_pct)::numeric, 2) AS median_pnl_pct,
  COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY sell_reason
ORDER BY count DESC;
```

#### 7-a. buy_reason_monthly — 매수 전략별 월간 성과

```sql
SELECT
  buy_reason,
  COUNT(*) AS buy_count,
  COUNT(*) FILTER (WHERE profit_loss_pct IS NOT NULL) AS closed_count,
  ROUND((AVG(profit_loss_pct))::numeric, 2) AS avg_pnl_pct,
  COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
FROM trades
WHERE trade_type = 'BUY'
  AND traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY buy_reason
ORDER BY buy_count DESC;
```

> 참고: BUY 레코드에는 `profit_loss_pct`가 NULL이므로, 매수 전략별 성과는 동일 종목의 후속 SELL과 매칭해야 한다. 정밀 분석이 필요하면 아래 보조 쿼리 사용:

```sql
SELECT
  t_buy.buy_reason,
  COUNT(DISTINCT t_buy.id) AS buy_count,
  COUNT(t_sell.id) AS matched_sell_count,
  ROUND((AVG(t_sell.profit_loss_pct))::numeric, 2) AS avg_sell_pnl_pct,
  COALESCE(SUM(t_sell.profit_loss_amount), 0) AS total_realized_pnl
FROM trades t_buy
LEFT JOIN trades t_sell
  ON t_buy.stock_code = t_sell.stock_code
  AND t_sell.trade_type = 'SELL'
  AND t_sell.traded_at > t_buy.traded_at
  AND t_sell.traded_at < t_buy.traded_at + INTERVAL '14 days'
WHERE t_buy.trade_type = 'BUY'
  AND t_buy.traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY t_buy.buy_reason
ORDER BY buy_count DESC;
```

#### 8. screening_monthly_conversion — 스크리닝 월간 전환율 (일별)

```sql
SELECT
  (screened_at AT TIME ZONE 'Asia/Seoul')::date AS screen_date,
  COUNT(DISTINCT stock_code) AS total_screened,
  COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true) AS converted,
  ROUND(100.0 * COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true)
    / NULLIF(COUNT(DISTINCT stock_code), 0), 1) AS conversion_rate_pct
FROM screening_results
WHERE screened_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (screened_at AT TIME ZONE 'Asia/Seoul')::date
ORDER BY screen_date;
```

#### 9. monthly_error_trend — 월간 에러 추이

```sql
SELECT
  ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date AS error_date,
  COUNT(*) AS error_count
FROM event_logs
WHERE timestamp >= (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'
  AND level = 'ERROR'
GROUP BY ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date
ORDER BY error_date;
```

#### 9-a. monthly_error_categories — 월간 에러 유형별 분류

```sql
SELECT
  category,
  COUNT(*) AS error_count,
  MIN(timestamp) AS first_seen_at,
  MAX(timestamp) AS last_seen_at
FROM event_logs
WHERE timestamp >= (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'
  AND level = 'ERROR'
GROUP BY category
ORDER BY error_count DESC;
```

#### 10. system_uptime_stats — 시스템 가동 통계

```sql
SELECT
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS total_cycles_started,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_END')   AS total_cycles_completed,
  COUNT(*) FILTER (WHERE metric_type = 'API_LIMIT')   AS api_limit_hits,
  COUNT(*) FILTER (WHERE metric_type = 'ERROR')       AS metric_errors,
  COUNT(*) FILTER (WHERE metric_type = 'RESTART')     AS restarts,
  COUNT(DISTINCT (recorded_at AT TIME ZONE 'Asia/Seoul')::date) AS trading_days
FROM system_metrics
WHERE recorded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul';
```

#### 11. 제안서 월간 현황 (파일시스템 + DB)

- 파일시스템: `docs/proposals/` 디렉토리에서 이번 달 KST 날짜(YYYY-MM-\*) 파일들을 읽어 상태별 집계.
- DB 보완:

```sql
SELECT title, category, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at;
```

각 제안서의 "기대 효과" 항목을 쿼리 1~10의 결과로 정량 검증한다.

---

### 2. 월간 성과 평가

위 쿼리 결과를 기반으로 작성한다.

- **월간 누적 손익·수익률** → 쿼리 1. 최종 `cumulative_pnl`과 `SUM(daily_pnl)/SUM(daily_buy_amount)×100`.
- **주차별 성과 추이** → 쿼리 2. 주별 `weekly_pnl` 변동과 `avg_pnl_pct` 추세.
- **최고/최저 성과 종목 TOP/BOTTOM 5** → 쿼리 3, 4.
- **시그널 유형별 월간 정확도** → 쿼리 5. `act_rate_pct`, `avg_confidence`의 월 전체 분포.
- **월간 승률 추이** → 쿼리 6. 일별 승률의 주간 이동평균과 최저 구간.
- **매도 사유 분포** → 쿼리 7. `STOP_LOSS` 비중, 중앙값 기준 손실 분포.
- **매수 전략별 성과** → 쿼리 7-a. 어떤 매수 전략(buy_reason)이 수익에 기여하는지.
- **스크리닝 전환율** → 쿼리 8. 월 평균 전환율과 일별 편차.
- **시스템 안정성** → 쿼리 9, 9-a, 10. 에러 카테고리, `api_limit_hits`, 재시작 횟수.

### 3. 전략 유효성 검증

#### a) MA(5/20) 전략 평가

쿼리 5에서 `GOLDEN_CROSS` / `DEAD_CROSS`의 월간 `act_rate_pct`·`avg_confidence`를 확인한다. 보조 쿼리로 시그널과 매수 체결의 근접 매칭을 분석:

```sql
SELECT
  t.stock_code, t.stock_name,
  s.signal_type,
  s.confidence, s.signal_value,
  t.profit_loss_pct, t.sell_reason,
  EXTRACT(EPOCH FROM (t.traded_at - s.detected_at))::int AS sec_from_signal
FROM trades t
JOIN signals s
  ON t.stock_code = s.stock_code
 AND s.action_taken = true
 AND s.signal_type IN ('GOLDEN_CROSS', 'DEAD_CROSS')
 AND t.traded_at BETWEEN s.detected_at AND s.detected_at + INTERVAL '10 minutes'
WHERE t.trade_type = 'BUY'
  AND t.traded_at >= date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
ORDER BY t.traded_at;
```

- 조인 윈도우는 **시그널 발생 ~ +10분**.
- `GOLDEN_CROSS`의 `avg(profit_loss_pct)` 가 음수이거나 평균 `confidence`와 실제 수익률의 상관이 약하면 → MA 기간 조정 또는 필터 추가 제안.

#### b) 리스크 파라미터 검증 (손절 3% / 익절 5%)

쿼리 7 결과로 `STOP_LOSS` / `TAKE_PROFIT` / `STRATEGY`의 분포를 확인한다. 4주 이상 매도 데이터 존재 여부:

```sql
SELECT COUNT(DISTINCT (traded_at AT TIME ZONE 'Asia/Seoul')::date) AS sell_days
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '28 days') AT TIME ZONE 'Asia/Seoul';
```

- `sell_days >= 20` → 통계 기반 손절/익절 임계값 조정 제안(중앙값, 분위수 활용).
- 미만 → "N주 후 재분석" 명시하고 보류.
- 손절 후 추가 하락폭·익절 후 추가 상승폭 분석은 현 스키마에 **매도 후 가격 추적 데이터**가 없어 불가. 필요 시 "post-sell price tracking 테이블 추가 제안" 작성.

#### c) 단순 매수보유 대비 초과수익 분석

- 현 스키마에 **일별 종가 기록 테이블이 없다**.
- DB에 없으면 이번 달 초과수익 분석은 **보류**하고, **"벤치마크 종가 적재 제안"** 을 작성한다. 제안서에는 아래를 포함:
  - 적재 대상 테이블 스키마 (예: `daily_prices(stock_code, trade_date, open, high, low, close, volume)`)
  - 적재 주기 (장 마감 후 1회)
  - 데이터 소스 (KIS API `FHKST01010100` 등)
  - 적재 후 재분석 시점 ("적재 시작 후 20 거래일 이상 축적 시 재실행")

### 4. 결과물

#### 월간 리포트
- 파일 경로: `docs/reports/YYYY-MM_monthly.md` (YYYY-MM은 **KST 기준** 이번 달)
- `docs/BRIDGE_SPEC.md`의 "월간 리포트 규격" 준수
- 섹션 구성: 월간 요약 / 주차별 추이 / 종목 TOP·BOTTOM / 시그널·리스크 평가 / 매수 전략별 성과 / 시스템 안정성 / 전략 방향성 판단 / 다음 달 액션 아이템
- 반드시 쿼리 번호와 결과(숫자·기간)를 근거로 인용

#### 중기/월간 제안서 (전략 방향 전환이 필요한 경우)
- 파일 경로: `docs/proposals/YYYY-MM-DD_제목.md` (YYYY-MM-DD는 KST 오늘)
- `docs/BRIDGE_SPEC.md` 제안서 규격 준수
- 상태: `ready`
- 한 제안서 = 한 변경 원칙
- 방향 전환성 변경은 **반드시 단계별 분할**하고, 첫 단계는 리스크 레벨 `safe` 또는 `moderate`.
- Claude Code가 즉시 구현 가능한 구체적 스펙으로 작성 (변경 파일, 변경 라인, 검증 방법, 롤백 조건 포함).

### 5. 주의사항

- 월간 리뷰는 **전략적 깊이 우선**, 분량 제한 없음. 주간 리포트의 단순 합산이 되지 않도록 **추세·구조적 원인·장기 리스크**에 집중한다.
- 그 외 공통 주의사항은 `_common_rules.md` 참조.
