# 주간 루틴 프롬프트 (Code 자동 실행용)

> 이 프롬프트는 `claude -p`로 비대화형 실행된다.
> launchd 스��줄: 금요일 18:00 KST

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 역할

너는 KIS 자동매매 시스템의 주간 통계 분석기야.
이번 주 데이터를 집계하고, 정형 통계 리포트를 생성하며, 전략별 성과를 수치로 정리한다.

> **주의**: 이 루틴은 정형 데이터 집계와 통계 작성만 수행한다.
> 중기 아키텍처 논의, 전략 방향성 판단 등 해석적 분석은 Cowork 세션에서 별도 수행��다.

## 작업 순서

### 1. 데이터 조회

PostgreSQL MCP로 이번 주 (월~오늘 KST) 데이터를 조회한다.

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

#### 4. risk_analysis — 매도 사유별 리스크

```sql
SELECT
  sell_reason, COUNT(*) AS count,
  ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pnl_pct,
  ROUND(MIN(profit_loss_pct)::numeric, 2) AS min_pnl_pct,
  ROUND(MAX(profit_loss_pct)::numeric, 2) AS max_pnl_pct,
  COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY sell_reason ORDER BY count DESC;
```

#### 4-a. buy_reason_performance — 매수 전략별 성과

```sql
SELECT
  t_buy.buy_reason,
  COUNT(DISTINCT t_buy.id) AS buy_count,
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
  category, COUNT(*) AS error_count
FROM event_logs
WHERE timestamp >= (date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'
  AND level = 'ERROR'
GROUP BY error_date, category
ORDER BY error_date, error_count DESC;
```

#### 7. cumulative_pnl — ��별 누적 손익

```sql
WITH daily AS (
  SELECT
    (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
    COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl
  FROM trades
  WHERE traded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
  GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date
)
SELECT trade_date, daily_pnl,
  SUM(daily_pnl) OVER (ORDER BY trade_date) AS cumulative_pnl
FROM daily ORDER BY trade_date;
```

#### 8. system_metrics — 시스템 요약

```sql
SELECT
  (recorded_at AT TIME ZONE 'Asia/Seoul')::date AS metric_date,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS cycles_started,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_END')   AS cycles_completed,
  COUNT(*) FILTER (WHERE metric_type = 'API_LIMIT')   AS api_limit_hits,
  COUNT(*) FILTER (WHERE metric_type = 'RESTART')     AS restarts
FROM system_metrics
WHERE recorded_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
GROUP BY (recorded_at AT TIME ZONE 'Asia/Seoul')::date
ORDER BY metric_date;
```

#### 9. implementation_logs — 이번 주 구현 이력

```sql
SELECT title, category, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= date_trunc('week', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at;
```

### 2. 주간 리포트 생성

`docs/reports/YYYY-Www_weekly.md` 파���을 생성한다.
`docs/BRIDGE_SPEC.md`의 주간 리포트 규격을 따른다.

#### 섹션별 매핑

| 리포트 섹션 | 데이터 소스 |
|-------------|-------------|
| 주간 요약 | 쿼리 1 합산 (총 매매, 손익, 승률) |
| 일별 추이 | 쿼리 1 그대로 표 |
| 종목별 성과 | 쿼리 2 (trade_count >= 3 종목 강조) |
| 시그널 전환율 | 쿼리 3 |
| 매수 전략별 성과 | 쿼리 4-a |
| 매도 사유 분포 | 쿼리 4 |
| 스크리닝 효율 | 쿼리 5 (일별 추이 + 주간 평균) |
| 에러 현황 | 쿼리 6 |
| 누적 손익 곡선 | 쿼리 7 (최대 drawdown 구간 언급) |
| 시스템 안정성 | 쿼리 8 |
| 이번 주 구현 현황 | 쿼리 9 |

#### "중기 아키텍처 논의" 및 "다음 주 액션 아이템" 섹션

이 두 섹션은 **데이터 요약만 제공**하고 판단은 비워둔다:

```markdown
## 중기 아키텍처 논의

> 아래 데이터를 기반으로 Cowork 세션에서 논의 예정

- cycles_started vs completed 차이: N건/주
- api_limit_hits: N회/주
- 시그널 유형별 act_rate 분산: [수치]
- 누적 손익 최대 drawdown: -N원 (MM-DD)

## 다음 주 액션 아이템

> Cowork 세션에서 결정 예정
```

### 3. 임계값 기반 제안서 (일간 루틴과 동일 룰)

일간 루틴의 룰 A~E를 주간 스코프(쿼리 3, 5, 6, 8)로 재평가한다.
일간에서 이미 생성된 제안서와 중복되면 skip.

### 4. 종��

- 생성한 파일 목록 출력
- 종료 코드 0
