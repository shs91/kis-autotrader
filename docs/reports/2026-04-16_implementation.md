# [2026-04-16] 자동 구현 리포트

## 요약
| 항목 | 값 |
|------|-----|
| 대상 제안서 (ready) | 2건 |
| implemented | 2건 |
| failed | 0건 |
| skipped | 0건 |
| needs_review | 0건 |

두 건 모두 `bug_fix` 카테고리의 observability 추가 제안으로, 기존 매매
로직에는 변경 없이 `Signal.meta`·`system_metrics` detail 필드만 확장.
BRIDGE_SPEC의 "5개 파일 한도", "금지 영역 미변경", "관련 테스트 동반
수정" 등 자동 안전 게이트를 모두 통과.

## 처리한 제안서

### 1. `2026-04-16_ensemble-all-hold-zero-confidence.md` — implemented

- **우선순위**: high, **카테고리**: bug_fix (observability)
- **변경 파일** (5개 정확히 충족):
  - `src/strategy/moving_average.py` — `series_len/nan_ratio/last_short/last_long/guard_triggered(+reason)` 기록
  - `src/strategy/rsi.py` — `series_len/nan_ratio/last_rsi/guard_triggered(+reason)` 기록, NaN 방어 분기 추가
  - `src/strategy/macd.py` — `series_len/nan_ratio/last_macd/last_signal/last_hist/guard_triggered(+reason)` 기록, NaN 방어 분기 추가
  - `src/strategy/bollinger.py` — `series_len/nan_ratio/last_price/last_upper/last_lower/last_percent_b/guard_triggered(+reason)` 기록, NaN 방어 분기 추가
  - `src/strategy/ensemble.py` — `_build_vote_meta()`에서 각 서브전략 Signal.meta를 vote에 병합 (기존 shape 키는 보호)
- **테스트 추가**: 5개 파일 (`test_ensemble.py` 1건 + 각 서브전략 테스트 파일 2건씩)
- **검증 결과**: pytest 400 passed / mypy 79→74 (-5) / ruff 16→16 (신규 에러 0)

### 2. `2026-04-16_screening-to-signal-pipeline-gap.md` — implemented

- **우선순위**: high, **카테고리**: bug_fix (observability)
- **변경 파일** (3개):
  - `src/engine.py` — `_record_eval_targets()` 메서드 + `run_trading_cycle` 내 호출 지점 추가. detail에 `{cycle, counts:{screening,watchlist,positions}, total_targets, targets(최대 50개), truncated}` 기록
  - `src/worker/screener.py` — ScreeningWorker ↔ 메인 엔진 간 `screening_results` 조회 규약을 모듈 docstring에 명문화
  - `src/strategy/selector.py` — `get_strategy()`에 전략 배정 DEBUG trace 1줄 추가
- **테스트 추가**: `tests/test_engine_db_integration.py`에 `TestRecordEvalTargets` 클래스 3건 (payload shape, truncate, run_trading_cycle 경로)
- **검증 결과**: pytest 400 passed / mypy 79→74 (-5) / ruff 16→16 (신규 에러 0)

## 검증 세부

### pytest
전체 400 passed + 4 pre-existing failures.

| 실패 테스트 | 원인 |
|-------------|------|
| `test_risk.py::TestShouldTakeProfit::test_custom_profit_ratio` | 오늘(2026-04-16) 날짜가 "장 마감 임박으로 신규 매수/익절 차단" 로직을 트리거 |
| `test_risk.py::TestValidateOrder::test_buy_with_sufficient_balance` | 동일 원인 |
| `test_risk.py::TestValidateOrder::test_buy_with_zero_balance_raises` | 동일 원인 |
| `test_risk.py::TestValidateOrder::test_buy_with_insufficient_balance_raises` | 동일 원인 |

모두 이번 변경과 무관한 pre-existing 실패 (`git stash` 후 동일하게 재현
확인). 제안서 자동 구현 안전 게이트 위반 아님.

### mypy / ruff
- 모두 pre-existing 에러만 존재. 변경 전 대비 신규 에러 0건.
- mypy는 오히려 5개 감소(타입 narrowing 개선 부수 효과).

## 실패한 건
없음.

## 후속 관찰 포인트 (내일 Cowork 리포트에서 확인)

1. `SIGNAL_SKIP.detail.vote_meta.votes[i]`에 `series_len / nan_ratio /
   guard_triggered` 등이 쌓이는지 확인.
2. `system_metrics.metric_type='EVAL_TARGETS'` 레코드가 매 사이클마다
   기록되는지 확인. 특히 `detail.counts.screening` 값이 0인지 양수인지가
   스크리닝 단절 경로 진단의 핵심 지표.
3. 위 두 관측 데이터를 기반으로 Cowork가 후속 수정 제안서를 작성할 수
   있어야 함 (본 제안들은 매매 성과 직접 개선 없음, 후속 제안의 근거
   제공).
