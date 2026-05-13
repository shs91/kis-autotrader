# 일간 루틴 프롬프트 (Code 자동 실행용)

> 이 프롬프트는 `claude -p`로 비대화형 실행된다.
> launchd 스케줄: 평일 16:30 KST (장 마감 후, auto-implement 전)

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 역할

너는 KIS 자동매매 시스템의 일간 데이터 분석기야.
오늘의 매매 데이터를 조회하고, 정형 리포트를 생성하며, 임계값 기반으로 제안서를 자동 작성한다.

## 실행 전 체크

```sql
SELECT COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS cycles_started
FROM system_metrics
WHERE (recorded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date;
```

`cycles_started = 0`이면 "시스템 비가동일 — 축약 리포트 생성" 모드로 전환.

## 작업 순서

### 1. 데���터 조회

PostgreSQL MCP(`mcp__postgres__query`)로 아래 쿼리를 순서대로 실행한다.

#### 1. daily_stats — 오늘의 매매 통계 + 승률

```sql
SELECT
  (traded_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
  COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0) AS win_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl,
  COALESCE(SUM(total_amount) FILTER (WHERE trade_type = 'BUY'), 0) AS total_buy_amount,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE trade_type = 'SELL' AND profit_loss_pct > 0)
    / NULLIF(COUNT(*) FILTER (WHERE trade_type = 'SELL'), 0), 1
  ) AS win_rate_pct
FROM trades
WHERE (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY (traded_at AT TIME ZONE 'Asia/Seoul')::date;
```

#### 2. stock_frequency — 오늘의 종목별 매매 빈도

```sql
SELECT
  stock_code, stock_name,
  COUNT(*) AS trade_count,
  COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
  COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
  COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl
FROM trades
WHERE (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY stock_code, stock_name
ORDER BY trade_count DESC;
```

#### 3. trade_detail — 오늘의 체결 상세

```sql
SELECT
  to_char(traded_at AT TIME ZONE 'Asia/Seoul', 'HH24:MI:SS') AS trade_time,
  stock_code, stock_name, trade_type, price, quantity,
  profit_loss_pct, buy_reason, sell_reason
FROM trades
WHERE (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
ORDER BY traded_at;
```

#### 4. signal_performance — 오늘의 시그널 성과

```sql
SELECT
  signal_type,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE action_taken = true) AS acted,
  ROUND(100.0 * COUNT(*) FILTER (WHERE action_taken = true) / NULLIF(COUNT(*), 0), 1) AS act_rate_pct,
  ROUND(AVG(confidence)::numeric, 3) AS avg_confidence
FROM signals
WHERE (detected_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY signal_type
ORDER BY total DESC;
```

#### 5. risk_analysis — 오늘�� 매도 사유별 리스크

```sql
SELECT
  sell_reason, COUNT(*) AS count,
  ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pnl_pct,
  ROUND(MIN(profit_loss_pct)::numeric, 2) AS min_pnl_pct,
  ROUND(MAX(profit_loss_pct)::numeric, 2) AS max_pnl_pct,
  COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
FROM trades
WHERE trade_type = 'SELL'
  AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY sell_reason ORDER BY count DESC;
```

#### 5-a. buy_reason_analysis — 오늘의 매수 사유별 분석

```sql
SELECT buy_reason, COUNT(*) AS buy_count
FROM trades
WHERE trade_type = 'BUY'
  AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY buy_reason ORDER BY buy_count DESC;
```

#### 6. screening_conversion — 오늘의 스크리닝 전환율

```sql
SELECT
  COUNT(DISTINCT stock_code) AS total_screened,
  COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true) AS converted,
  ROUND(100.0 * COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true)
    / NULLIF(COUNT(DISTINCT stock_code), 0), 1) AS conversion_rate_pct
FROM screening_results
WHERE (screened_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date;
```

#### 7. error_summary — 오늘의 에러 요약

```sql
SELECT category, COUNT(*) AS error_count, MAX(timestamp) AS last_occurred_at
FROM event_logs
WHERE ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
  AND level = 'ERROR'
GROUP BY category ORDER BY error_count DESC;
```

#### 8. intraday_cumulative_pnl — 장중 누적 손익

```sql
WITH today_sells AS (
  SELECT
    (traded_at AT TIME ZONE 'Asia/Seoul') AS kst_time,
    stock_code, stock_name,
    COALESCE(profit_loss_amount, 0) AS pnl_amount,
    profit_loss_pct
  FROM trades
  WHERE trade_type = 'SELL'
    AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
)
SELECT kst_time, stock_code, stock_name, profit_loss_pct, pnl_amount,
  SUM(pnl_amount) OVER (ORDER BY kst_time) AS cumulative_pnl
FROM today_sells ORDER BY kst_time;
```

#### 9. system_metrics_summary — 사이클/API 요약

```sql
SELECT
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS cycles_started,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_END')   AS cycles_completed,
  COUNT(*) FILTER (WHERE metric_type = 'API_LIMIT')   AS api_limit_hits,
  COUNT(*) FILTER (WHERE metric_type = 'ERROR')       AS metric_errors
FROM system_metrics
WHERE (recorded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date;
```

#### 10. rolling_7d_signals — 최근 7일 시그널 (제안서 근거용)

```sql
SELECT signal_type,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE action_taken = true) AS acted,
  ROUND(100.0 * COUNT(*) FILTER (WHERE action_taken = true) / NULLIF(COUNT(*), 0), 1) AS act_rate_pct,
  ROUND(AVG(confidence)::numeric, 3) AS avg_confidence
FROM signals
WHERE detected_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '6 days') AT TIME ZONE 'Asia/Seoul'
GROUP BY signal_type ORDER BY total DESC;
```

#### 11. rolling_7d_screening — 최근 7일 스크리닝 전환율

```sql
SELECT
  (screened_at AT TIME ZONE 'Asia/Seoul')::date AS screen_date,
  COUNT(DISTINCT stock_code) AS total_screened,
  COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true) AS converted,
  ROUND(100.0 * COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true)
    / NULLIF(COUNT(DISTINCT stock_code), 0), 1) AS conversion_rate_pct
FROM screening_results
WHERE screened_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '6 days') AT TIME ZONE 'Asia/Seoul'
GROUP BY (screened_at AT TIME ZONE 'Asia/Seoul')::date ORDER BY screen_date;
```

#### 12. sell_data_sufficiency — 28일 매도 데이터 충분성

```sql
SELECT COUNT(DISTINCT (traded_at AT TIME ZONE 'Asia/Seoul')::date) AS sell_days
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '28 days') AT TIME ZONE 'Asia/Seoul';
```

### 2. 리포트 생성

`docs/reports/YYYY-MM-DD_daily.md` 파일을 생성한다 (YYYY-MM-DD는 KST 오늘).
`docs/BRIDGE_SPEC.md`의 일일 리포트 규격을 따른다.

**시스템 비가동일 모드**: cycles_started = 0이면:
- 요약에 "시스템 비가동 — 매매 사이클 미실행" 명시
- 체결 상세·시그널·스크리닝 ��션 생략
- 에러·시스템 상태만 기록

**정상 모드**: 쿼리 1~9 결과를 BRIDGE_SPEC 템플릿에 매핑:
- 매매 요약: 쿼리 1 (수익률 = total_pnl / total_buy_amount × 100, 매수 0건이면 "N/A")
- 체결 상세: 쿼리 3 (BUY→buy_reason, SELL→sell_reason을 "사유"열에 표시)
- 시그널 분석: 쿼�� 4
- 매수 전략별: 쿼리 5-a
- 스크리닝 효율: 쿼리 6
- 시스템 상태: 쿼리 7, 9
- 장중 누적 ��익: 쿼리 8

### 3. 임계값 기반 자동 제안서 (룰 엔진)

아래 조건을 **순서대로** 체크한다. 하나��도 해당되면 `docs/proposals/YYYY-MM-DD_제목.md`를 생성한다.
한 제안서 = 한 변경 원칙. 최대 2건/일.

#### 룰 A: 시그널 전환율 저하
- **조건**: 쿼리 10에서 특정 signal_type의 7일 `act_rate_pct < 50%` 이고 `avg_confidence < 0.3`
- **제안**: 해당 전략의 MIN_CONFIDENCE 상향 또는 기간 파라미터 조정
- **참조**: BRIDGE_SPEC 파라미터 허용 범위 테이블

#### 룰 B: 스크리닝 전환율 악화
- **조건**: 쿼리 11에서 최근 3일 연속 `conversion_rate_pct < 10%`
- **제안**: SCREENING_MIN_SCORE 상향 또는 SCREENING_MIN_VOLUME 조정
- **참조**: BRIDGE_SPEC 파라미터 허용 범위 테이블

#### 룰 C: 시스템 에러 반복
- **조건**: 쿼리 7에서 동일 category가 3건 이상 이고, 전일에도 같은 category 에러 존재
- **제안**: 해당 에러의 원인 코드 수정 (카테고리에 따라 변경 대상 파일 특정)

#### 룰 D: API 한도 도달
- **조건**: 쿼리 9의 `api_limit_hits > 0`
- **제안**: SCREENING_INTERVAL_CYCLES 증가 또는 SCREENING_TOP_N 감소

#### 룰 E: 리스크 파라미터 (데이터 충분 시만)
- **전제조건**: 쿼리 12의 `sell_days >= 20`
- **조건**: 쿼리 5에서 `STOP_LOSS` 평균 손실률이 현재 MAX_LOSS_RATE보다 0.5%p 이상 크거나 작음
- **제안**: MAX_LOSS_RATE 조정 (BRIDGE_SPEC 범위 내)

**제안서 포맷**: `docs/BRIDGE_SPEC.md` 제안서 규격 준수. 근거 섹션에 쿼리 번호와 수치 인용 필수.

### 4. 종료

- 생성한 파일 목록을 stdout으�� 출력
- 제안서가 생성되었으면 "제안서 N건 생성 → auto-implement에서 처리 예정" 출력
- 에러 없이 완료되면 종료 코드 0
