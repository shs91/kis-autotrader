# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (72건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-11] 앙상블 시그널 최소 신뢰도 2차 상향 (0.15→0.20)
- 제안서: docs/proposals/2026-05-11_ensemble-confidence-further-raise.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `STRATEGY_MIN_CONFIDENCE` 0.15 → 0.20. W19 전환율 19.7% / 평균 신뢰도 0.238 대비 저신뢰 시그널 추가 필터링.
- 검증 결과: pytest ✅ (429 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-05-11] 일봉 조회 페이지네이션 — 60일 데이터 확보로 MACD 활성화
- 제안서: docs/proposals/2026-05-09_daily-quote-pagination-60days.md
- 카테고리: performance
- 변경 파일:
  - src/api/quote.py: `get_daily_price`에 `lookback_days` 파라미터 + 30건 단위 페이지네이션 루프 추가. 기본 60건 확보.
  - tests/test_api/test_quote.py: 페이지네이션 60건 확보 테스트, 단일 페이지 테스트 2건 추가.
- 검증 결과: pytest ✅ (429 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-05-11] 스크리너 ETF/Q-code 필터 누수 수정 — 코드 기반 블록리스트 도입
- 제안서: docs/proposals/2026-05-09_screener-etf-code-blocklist.md
- 카테고리: bug_fix
- 변경 파일:
  - config/etf_blocklist.json: ETF 코드 블록리스트 신규 생성 (10종목).
  - src/strategy/screener.py: 블록리스트 로드 + stock_name 결손 차단 + `_is_etf_etn` 보강.
  - src/worker/screener.py: DB INSERT 직전 ETF 재검증 추가.
  - tests/test_strategy/test_screener.py: 블록리스트·이름결손 테스트 3건 추가.
- 검증 결과: pytest ✅ (429 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-05-08] 스크리닝 종목 시그널 품질 진단 메트릭 추가
- 제안서: docs/proposals/2026-05-08_screening-signal-quality-metric.md
- 카테고리: performance
- 변경 파일:
  - src/engine.py: 스크리닝 종목 BUY/SELL/HOLD 카운터 3개 추가 (`_cycle_screening_buy/sell/hold`). SIGNAL_SUMMARY 메트릭에 `screening_buy`, `screening_sell`, `screening_hold` 필드 추가.
  - tests/test_engine_db_integration.py: SIGNAL_SUMMARY expected_keys에 screening 필드 3개 추가.
- 검증 결과: pytest ✅ (424 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-05-07] 스크리닝 최소 점수 하향 — 전환율 0% 장기화 해소
- 제안서: docs/proposals/2026-05-07_screening-min-score-reduction.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `SCREENING_MIN_SCORE` 0.25(기본값) → 0.15 하향 추가. 7일 연속 전환율 0% 교착 해소 목적.
- 검증 결과: pytest ✅ (424 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만
