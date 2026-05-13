# 공통 규칙 (모든 분석 프롬프트 적용)

## 타임존 규칙

- DB의 timestamp는 UTC로 저장된다.
- `trades.traded_at`, `signals.created_at/detected_at`, `screening_results.screened_at`, `system_metrics.recorded_at`는 `timestamptz` (timezone-aware).
- `event_logs.timestamp`만 naive UTC다 (timezone 정보 없음).
- 모든 날짜 경계·그룹핑은 `AT TIME ZONE 'Asia/Seoul'`로 KST 변환한다.
- `event_logs` 쿼리 시에는 `(timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Seoul'`로 변환한다.
- `signals` 시간 필터는 항상 `detected_at`을 사용한다 (`created_at`은 DB 메타데이터). `trades` JOIN 윈도우에서도 `detected_at` 기준으로 조인한다.

## DB Enum 값 목록

| 테이블 | 컬럼 | 값 |
|--------|------|-----|
| `event_logs` | `level` | `INFO` / `WARNING` / `ERROR` (CRITICAL 없음, 사용 금지) |
| `system_metrics` | `metric_type` | `CYCLE_START` / `CYCLE_END` / `API_LIMIT` / `ERROR` / `RESTART` |
| `trades` | `trade_type` | `BUY` / `SELL` |
| `trades` | `buy_reason` | `GOLDEN_CROSS` / `RSI_OVERSOLD` / `ENSEMBLE` / `MANUAL` |
| `trades` | `sell_reason` | `STOP_LOSS` / `TAKE_PROFIT` / `STRATEGY` / `MANUAL` |
| `signals` | `signal_type` | `GOLDEN_CROSS` / `DEAD_CROSS` / `RSI_OVERSOLD` / `RSI_OVERBOUGHT` 등 |

## 수익률 정의

- **개별 매도 수익률**: `trades.profit_loss_pct` (매수 평균가 대비 매도 가격의 변동률 %)
- **일일 수익률**: `SUM(profit_loss_amount) / SUM(total_amount WHERE trade_type='BUY') × 100` (당일 매수 총액 대비 실현 손익)
- 계좌 총액 대비 수익률은 현 스키마에 계좌 잔고 테이블이 없으므로 산출 불가. 당일 매수 총액 대비로 통일한다.
- 매수가 0건이고 매도만 있는 경우(전일 매수 → 당일 매도), 수익률 분모는 해당 매도 건의 `(price - profit_loss_amount/quantity) × quantity`로 역산한 매수 총액을 사용한다.

## 승률 정의

- **승률** = `profit_loss_pct > 0`인 매도 건수 / 전체 매도 건수 × 100
- 매도 0건이면 승률은 "N/A"로 표기한다.

## 매매 0건 날 처리

- 오늘 매매 0건이더라도 리포트는 작성한다 (시그널·스크리닝·에러·사이클 데이터가 존재할 수 있음).
- 단, `system_metrics`에서 `CYCLE_START`가 0건이면 "시스템 비가동일"로 판단하고 리포트를 축약한다:
  - 요약 섹션에 "시스템 비가동 — 매매 사이클 미실행" 명시
  - 체결 상세·시그널·스크리닝 섹션 생략
  - 에러·시스템 상태 섹션만 작성

## 제안서 작성 임계값 (정량 기준)

| 지표 | 임계값 | 조건 |
|------|--------|------|
| 시그널 전환율 저하 | `act_rate_pct < 50%` | 최근 7일 평균 기준 |
| confidence 지속 저하 | 7일 평균 `avg_confidence < 0.3` 이고 전주 대비 하락 | 최소 5거래일 데이터 필요 |
| 스크리닝 전환율 악화 | 7일 이동평균 전환율 < 10% | 3일 연속 미달 시 제안 |
| 에러 반복 | 동일 category 에러 3일 연속 또는 일 5건 이상 | — |
| API 한도 도달 | `api_limit_hits > 0` 2일 이상 연속 | — |

## implementation_logs 활용

제안서 효과 검증 시 파일시스템(`docs/proposals/`)과 DB를 병행한다:

```sql
SELECT title, proposal_path, expected_effect, implemented_at
FROM implementation_logs
WHERE implemented_at >= ((now() AT TIME ZONE 'Asia/Seoul')::date - INTERVAL '14 days')
  AT TIME ZONE 'Asia/Seoul'
ORDER BY implemented_at DESC;
```

## 공통 주의사항

- `.env`, `credentials.json`, `token.json` 절대 읽지 마.
- Python 스크립트를 직접 실행하지 않는다. 모든 데이터 조회는 PostgreSQL MCP를 통해 수행한다.
- 데이터 부족 시 추측 금지: **"데이터 축적 필요 — N일 이상 데이터 축적 후 재분석"** 으로 명시.
- 리포트·제안서는 한국어로 작성한다.
- 파일명 날짜는 반드시 **KST 기준**으로 결정한다.
