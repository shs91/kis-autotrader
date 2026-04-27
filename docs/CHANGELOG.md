# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (59건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-04-27 21:00] 시그널 가뭄 진단 정보 DB 적재 — SIGNAL_SUMMARY 메트릭
- 제안서: docs/proposals/2026-04-27_signal-diagnosis-db-persistence.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: 사이클 종료 시 `_record_metric("SIGNAL_SUMMARY", {...})` 호출 추가. cycle/evaluated/buy_count/sell_count/hold_count/max_confidence/screened_count를 system_metrics 테이블에 기록.
  - tests/test_engine_db_integration.py: `TestSignalSummaryMetric` 클래스 추가 (사이클 후 SIGNAL_SUMMARY 기록 검증, 필수 키 존재 검증, 평가 0건 시 미기록 검증 — 3개 테스트).
- 검증 결과: pytest ✅ (414 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-04-24 21:00] 시그널 가뭄 진단 로깅 추가
- 제안서: docs/proposals/2026-04-24_signal-drought-diagnosis-logging.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: 사이클별 전략 평가 카운터(`_cycle_buy_count`, `_cycle_sell_count`, `_cycle_hold_count`, `_cycle_max_confidence`) 추가. 사이클 종료 시 평가 요약 INFO 로그 출력.
- 검증 결과: pytest ✅ (411 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-04-24 21:00] 앙상블 HOLD 과반 가드 임계값 완화 — 50% → 75%
- 제안서: docs/proposals/2026-04-24_ensemble-hold-threshold-relaxation.md
- 카테고리: refactor
- 변경 파일:
  - src/strategy/ensemble.py: `_weighted_vote` 내 HOLD 가드 임계값 `len(signals) / 2` → `len(signals) * 3 / 4` 변경. 4개 전략 중 3개 HOLD + 1개 BUY 시 weighted vote 진행 허용.
  - tests/test_strategy/test_ensemble.py: HOLD 과반 가드 테스트를 새 임계값(75%)에 맞게 수정. `test_weighted_hold_3_of_4_passes_through` 테스트 추가.
- 검증 결과: pytest ✅ | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-04-24 21:00] 스크리너 ETF/ETN/레버리지 종목 필터링 추가
- 제안서: docs/proposals/2026-04-24_screener-etf-filter.md
- 카테고리: refactor
- 변경 파일:
  - src/strategy/screener.py: `ScreeningFilter._is_etf_etn()` 정적 메서드 추가 (종목코드 Q 시작 또는 종목명에 KODEX/TIGER/KBSTAR/ARIRANG/SOL/ACE/HANARO/ETN/레버리지/인버스/2X/곱버스 포함 시 필터링). `apply()` 및 `_pass_filter()`에서 ETF/ETN 종목 제외. 필터 로그에 ETF/ETN 제외 건수 추가.
  - tests/test_strategy/test_screener.py: `TestETFFilter` 클래스 추가 (KODEX/TIGER/ETN코드/레버리지 필터링 + 일반 종목 통과 + 통합 필터링 6개 테스트).
- 검증 결과: pytest ✅ | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-04-24 21:00] 스크리닝 가중치 재조정 + MA 기간 단축 + 최소 신뢰도 하향
- 제안서:
  - docs/proposals/2026-04-24_screening-weight-rebalance.md
  - docs/proposals/2026-04-24_ma-period-shortening.md
  - docs/proposals/2026-04-24_min-confidence-lowering.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `SCREENING_WEIGHT_VOLUME_RANK` 0.2→0.3, `SCREENING_WEIGHT_CHANGE_RATE` 0.3→0.4, `SCREENING_WEIGHT_STRATEGY` 0.5→0.3 (합계 1.0), `STRATEGY_MA_SHORT_PERIOD` 5→3, `STRATEGY_MIN_CONFIDENCE` 0.1→0.08
  - tests/test_strategy/test_moving_average.py: `test_default_init` 기대값을 config에서 동적 로드하도록 수정 (config_overrides 영향 반영)
- 검증 결과: pytest ✅ (411 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅
