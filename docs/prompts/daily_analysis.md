# 일간 분석 프롬프트

## 공통 규칙

`docs/prompts/_common_rules.md`를 먼저 읽고 적용할 것.

## 역할

너는 KIS 자동매매 시스템의 분석가 겸 전략 기획자야.
PostgreSQL에 적재된 오늘의 매매 데이터를 분석하고, 개선이 필요하면 제안서를 작성해.

## 작업 순서

### 0. 컨텍스트 로딩

- CLAUDE.md → 프로젝트 구조, 전략, 파라미터
- docs/BRIDGE_SPEC.md → 리포트 규격, 제안서 규격, 안전 게이트 규칙
- docs/prompts/_common_rules.md → 타임존, enum, 수익률/승률 정의

### 1. 데이터 조회

PostgreSQL MCP를 사용해 직접 쿼리한다.

**스코프 규칙**
- **쿼리 1~9 → 오늘 KST** (일일 리포트 본문용)
- **쿼리 10, 11 → 최근 7일 rolling** (제안서 근거용, 월요일 빈 표본 방지)
- **쿼리 12 → 최근 28일 rolling** (데이터 충분성 판단용)
- 리포트 본문에는 반드시 "오늘" 데이터(쿼리 1~9)만 사용하고, 제안서 근거에 한해 10~12를 참조한다.

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
  stock_code,
  stock_name,
  trade_type,
  price,
  quantity,
  profit_loss_pct,
  buy_reason,
  sell_reason
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
WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY signal_type
ORDER BY total DESC;
```

#### 5. risk_analysis — 오늘의 매도 사유별 리스크

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
  AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY sell_reason
ORDER BY count DESC;
```

#### 5-a. buy_reason_analysis — 오늘의 매수 사유별 분석

```sql
SELECT
  buy_reason,
  COUNT(*) AS buy_count
FROM trades
WHERE trade_type = 'BUY'
  AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY buy_reason
ORDER BY buy_count DESC;
```

#### 6. screening_conversion — 오늘의 스크리닝 전환율

```sql
SELECT
  (screened_at AT TIME ZONE 'Asia/Seoul')::date AS screen_date,
  COUNT(DISTINCT stock_code) AS total_screened,
  COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true) AS converted,
  ROUND(100.0 * COUNT(DISTINCT stock_code) FILTER (WHERE converted_to_trade = true)
    / NULLIF(COUNT(DISTINCT stock_code), 0), 1) AS conversion_rate_pct
FROM screening_results
WHERE (screened_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY (screened_at AT TIME ZONE 'Asia/Seoul')::date;
```

#### 7. error_trend — 오늘의 에러 건수

```sql
SELECT
  ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date AS error_date,
  COUNT(*) AS error_count
FROM event_logs
WHERE ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
  AND level = 'ERROR'
GROUP BY ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date;
```

#### 7-a. error_categories — 오늘의 에러 유형별 분류

```sql
SELECT
  category,
  COUNT(*) AS error_count,
  MAX(timestamp) AS last_occurred_at
FROM event_logs
WHERE ((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
  AND level = 'ERROR'
GROUP BY category
ORDER BY error_count DESC;
```

#### 8. intraday_cumulative_pnl — 오늘의 체결 시퀀스별 누적 손익

```sql
WITH today_sells AS (
  SELECT
    (traded_at AT TIME ZONE 'Asia/Seoul') AS kst_time,
    stock_code,
    stock_name,
    COALESCE(profit_loss_amount, 0) AS pnl_amount,
    profit_loss_pct
  FROM trades
  WHERE trade_type = 'SELL'
    AND (traded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
)
SELECT
  kst_time,
  stock_code,
  stock_name,
  profit_loss_pct,
  pnl_amount,
  SUM(pnl_amount) OVER (ORDER BY kst_time) AS cumulative_pnl
FROM today_sells
ORDER BY kst_time;
```

#### 9. system_metrics_summary — 오늘의 사이클/API 한도 요약

```sql
SELECT
  (recorded_at AT TIME ZONE 'Asia/Seoul')::date AS metric_date,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_START') AS cycles_started,
  COUNT(*) FILTER (WHERE metric_type = 'CYCLE_END')   AS cycles_completed,
  COUNT(*) FILTER (WHERE metric_type = 'API_LIMIT')   AS api_limit_hits,
  COUNT(*) FILTER (WHERE metric_type = 'ERROR')       AS metric_errors
FROM system_metrics
WHERE (recorded_at AT TIME ZONE 'Asia/Seoul')::date = (now() AT TIME ZONE 'Asia/Seoul')::date
GROUP BY (recorded_at AT TIME ZONE 'Asia/Seoul')::date;
```

---

#### 10. strategy_ma_signals — 최근 7일 MA 교차 시그널 (제안서 근거용)

```sql
SELECT
  signal_type,
  confidence,
  signal_value,
  action_taken,
  detected_at
FROM signals
WHERE signal_type IN ('GOLDEN_CROSS', 'DEAD_CROSS')
  AND created_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '6 days') AT TIME ZONE 'Asia/Seoul'
ORDER BY created_at;
```

#### 11. strategy_rsi_existence — 최근 7일 RSI 시그널 존재 여부

```sql
SELECT COUNT(*) AS rsi_signal_count
FROM signals
WHERE signal_type LIKE '%RSI%'
  AND created_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '6 days') AT TIME ZONE 'Asia/Seoul';
```

#### 12. sell_data_sufficiency — 최근 28일 매도 데이터 충분성

```sql
SELECT COUNT(DISTINCT (traded_at AT TIME ZONE 'Asia/Seoul')::date) AS sell_days
FROM trades
WHERE trade_type = 'SELL'
  AND traded_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '28 days') AT TIME ZONE 'Asia/Seoul';
```

#### 13. recent_implementations — 최근 14일 구현 이력 (효과 검증용)

```sql
SELECT title, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '14 days')
  AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at DESC;
```

각 쿼리 결과를 종합해서 아래 분석 작업에 활용한다.

### 2. 일일 리포트 작성

- `docs/reports/YYYY-MM-DD_daily.md` 파일로 저장 (YYYY-MM-DD는 KST 기준 오늘 날짜)
- `docs/BRIDGE_SPEC.md`의 "일일 리포트 규격"을 정확히 따르되, 아래 섹션을 DB 데이터 기반으로 작성한다.

#### 매매 요약
- 총 매수 N건, 매도 N건 (← 쿼리 1)
- 실현 손익: +/-N원 (수익률: total_pnl / total_buy_amount × 100%) (← 쿼리 1)
- 승률: N% (win_count / sell_count) (← 쿼리 1의 win_rate_pct)
- 매수 0건이면 수익률은 "N/A"로 표기

#### 체결 상세
| 시각 | 종목 | 유형 | 가격 | 수량 | 손익률 | 사유 |

쿼리 3 결과를 표로 렌더링. BUY는 buy_reason, SELL은 sell_reason을 "사유" 열에 표시.

#### 시그널 분석 (← 쿼리 4)
- 시그널 유형별 발생 건수, 매매전환 건수, 전환율, 평균 confidence
- **"시그널 정확도"는 `action_taken` 전환율과 평균 `confidence`로 정의한다.** 사후 수익률 연결은 현 스키마상 signals ↔ trades 근접 조인이 필요해 단순 집계가 불가능하므로, 향후 스키마 확장 시 재검토한다.

#### 매수 전략별 분석 (← 쿼리 5-a)
- 매수 사유별 건수: GOLDEN_CROSS N건, RSI_OVERSOLD N건, ENSEMBLE N건, MANUAL N건

#### 스크리닝 효율 (← 쿼리 6)
- 발굴 N종목, 매매전환 N종목 (전환율 N%)

#### 시스템 상태 (← 쿼리 7, 7-a, 9)
- 매매 사이클 N회 실행 (started / completed)
- 에러 N건 (유형별 분류: category별 count)
- API 한도 도달 여부 (`api_limit_hits` > 0)
- `cycles_started = 0`이면 "시스템 비가동일" 명시, 체결·시그널·스크리닝 섹션 생략

#### 장중 누적 손익 (← 쿼리 8)
- 매도 체결 시각순 누적 손익 곡선 요약 (최대 수익·최대 손실 구간 언급)

### 3. 이전 제안서 효과 검증 (조건부)

**쿼리 13에서 최근 14일 이내 구현 이력이 있을 때만** 수행한다.

- 쿼리 13 결과 + `docs/proposals/`에서 해당 제안서 파일을 읽어 "기대 효과"를 확인한다.
- 각 제안서의 "기대 효과" 항목을 DB 데이터로 정량 검증한다.
  - 예: "승률 5% 개선" → 구현 전/후 기간의 `profit_loss_pct > 0` 비율 비교.
- 효과가 미달(또는 역효과)이면 섹션 4의 후속 제안서 작성을 우선 고려한다.
- 이미 검증 완료된 제안서(이전 리포트에서 결론 도출)는 skip.

### 4. 개선 제안서 작성 (필요 시에만)

DB 데이터가 뒷받침하는 경우에만 작성한다. 쿼리 10~12의 rolling window 데이터를 근거로 사용한다.
임계값은 `_common_rules.md`의 "제안서 작성 임계값" 테이블 참조.

- **a) 전략 시그널**: 쿼리 4(오늘) + 쿼리 10(최근 7일)에서 7일 평균 `act_rate_pct < 50%` 또는 7일 평균 `avg_confidence < 0.3`이고 전주 대비 하락 → 파라미터 조정 제안
- **b) 리스크 파라미터**: 쿼리 5(오늘) 매도 사유별 분포 + 쿼리 12가 20일 이상일 때만 → 손절/익절 임계값 조정 근거 제시. 미만이면 "데이터 축적 필요"로 보류.
- **c) 시스템 안정성**: 쿼리 7·7-a·9에서 동일 category 에러 3일 연속 또는 일 5건 이상, `api_limit_hits > 0` 2일 이상 연속 → 코드/스케줄 개선 제안
- **d) 스크리닝 효율**: 쿼리 6 전환율 7일 이동평균 < 10% 이고 3일 연속 미달 → 필터 기준 강화 제안
- **e) 파라미터 튜닝**: 쿼리 10·11·12 데이터 분포 분석 → `config_overrides.json` 파라미터 조정 제안. **반드시** `docs/BRIDGE_SPEC.md` 허용 범위 테이블 참조, 가중치 합 = 1.0 제약 준수.

**제안서 작성 규칙**
- 파일 경로: `docs/proposals/YYYY-MM-DD_제목.md` (YYYY-MM-DD는 KST 기준 오늘)
- `docs/BRIDGE_SPEC.md`의 제안서 규격 준수
- 상태: `ready`
- 한 제안서 = 한 변경 원칙
- 쿼리 결과(숫자, 기간)를 근거 섹션에 반드시 인용

### 5. 주의사항

- 쿼리 1~9 스코프는 **오늘 KST 하루**, 쿼리 10~11은 **최근 7일**, 쿼리 12는 **최근 28일**. 섹션별 스코프 혼동 금지.
- 그 외 공통 주의사항은 `_common_rules.md` 참조.
