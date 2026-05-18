# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (80건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-17] 텔레그램 /help 누락 명령 추가 — /run_implement /status_implement /pause_implement (v0.2.7)
- 카테고리: bug_fix
- 변경 파일:
  - main.py: `cmd_help` 문자열에 `/run_implement [--dry|--force]`, `/status_implement`, `/pause_implement [resume]` 3줄 추가. 명령 등록(L540-542)은 정상이었으나 help 하드코딩에서 빠져 사용자가 발견할 수 없던 문제.
- 배경: 텔레그램에서 `/help` 입력 시 하네스 관련 명령 3개가 표시되지 않음. register는 정상이라 명령 자체는 동작했으나 사용자가 존재 자체를 알기 어려움.
- 영향: 사용자가 `/help`만 보고도 하네스 자동 구현 명령(`/run_implement`, `/status_implement`, `/pause_implement`)을 발견·사용 가능.
- 검증 결과: ruff ✅ All checks passed | mypy ✅ (변경 라인 신규 에러 0, 기존 3건은 무관) | 재시작 후 헬스 ok 확인.

---

## [2026-05-16] 일봉 조회 엔드포인트 교체 — `inquire-daily-itemchartprice`로 60건 데이터 실제 확보 + MACD 정상 가동 (v0.2.6) — 🔴 핫픽스
- 제안서: docs/proposals/2026-05-16_daily-quote-endpoint-switch-itemchartprice.md
- 카테고리: bug_fix
- 변경 파일:
  - src/api/quote.py: `DAILY_PRICE_PATH` → `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, `TR_ID_DAILY_PRICE` → `FHKST03010100`. `get_daily_price()` 본문 재작성 — 페이지네이션 루프 제거, 1차 호출(`lookback_days * 2`/최소 60일 윈도우) + 부족 시 fallback 1회 한정. 응답 파싱은 `output2 → output` fallback으로 신·구 엔드포인트 모두 호환.
  - tests/test_api/test_quote.py: 기존 4개 케이스를 `output2` 응답으로 재작성, 신규 4건 추가(`test_get_daily_price_uses_itemchartprice_endpoint`, `test_get_daily_price_single_call_returns_60_items`, `test_get_daily_price_handles_100_items`, `test_get_daily_price_fallback_second_call`). 미사용 import 정리.
- 배경: W19~W20 기간 동안 `series_len`이 30으로 고정되어 MACD가 영구 비활성화됨. 페이지네이션 코드는 이미 적용됐으나 `inquire-daily-price` 엔드포인트가 일자 파라미터를 무시하여 항상 동일 30건만 반환. 진짜 차단 지점은 엔드포인트 선택이었다.
- 영향: 1회 호출로 최대 100건 일봉 확보. `series_len`이 `ma_long_period + 2` 이상으로 회복되어 MACD/볼린저 등 장기 지표 정상 가동. KIS API 호출량도 페이지네이션 4~5회 → 1회로 감소(rate-limit 안전 마진 확보).
- 검증 결과: pytest `tests/test_api/test_quote.py` ✅ 11/11 (신규 4건 포함) | 전체 회귀 ✅ 신규 회귀 0건 (6 pre-existing fail baseline 동일) | mypy 변경 라인 에러 없음 | ruff 위반 2건 개선(F401), 신규 위반 0.

---

## [2026-05-15] 스크리닝→매매 매핑 진단 메트릭 추가 (SCREENING_CANDIDATE / SCREENING_HIT·MISS) (v0.2.5)
- 제안서: docs/proposals/2026-05-15_screening-conversion-diagnostic-metric.md
- 카테고리: performance
- 변경 파일:
  - src/worker/screener.py: `_record_to_db` 안에서 `SystemMetricRepository.record_metric`으로 `SCREENING_CANDIDATE` 1건 기록 (`cycle / ranked_total / candidate_count`).
  - src/engine.py: `_execute_buy` 체결 직후 `_record_screening_match_metric(stock_code)` 헬퍼 호출 — 당일 KST 기준 `screening_results`에 동일 stock_code 존재 시 `SCREENING_HIT`, 없으면 `SCREENING_MISS`. 매수 본 흐름과 분리(예외 swallow).
  - tests/test_worker/test_screener.py: `SCREENING_CANDIDATE` 기록 검증 2건 + ranked item 헬퍼 추가.
  - tests/test_engine_db_integration.py: HIT/MISS/예외/`_execute_buy` 통합 호출 검증 4건 추가.
- 배경: 룰 B(3일 연속 스크리닝 전환율 <10%) 트리거. 현 `converted_to_trade`는 워커 자체 추천 후보 마킹일 뿐 실제 매수와 매핑되지 않아 룰 B 의미가 모호. 5-14는 BUY 3건 + 스크리닝 전환 0건, 5-15는 BUY 0건 + 전환 0건이 동일하게 "전환율 0%"로 보여 진단 변별력 부재.
- 영향: 1~2주 누적 후 룰 B 측정값을 (워커 후보 / 엔진 매수 / 매핑 일치율)로 분해 가능. 무차별 임계값 조정으로 인한 매매 위축 위험 회피. 기록 실패 시 fallback 처리되어 매매·스크리닝 본 흐름에 영향 없음.
- 검증 결과: pytest ✅ 470 passed, 5 pre-existing fail(KST 시간대 의존) | mypy 변경 라인 에러 없음 (66 pre-existing 동일) | ruff src/ 16 pre-existing 동일.

---

## [2026-05-13] engine.py의 메트릭·시그널 큐 적재 시 naive timestamp 차단 버그 수정 (v0.2.4) — 🔴 핫픽스
- 제안서: docs/proposals/2026-05-13_engine-metric-signal-naive-timestamp-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_record_signal_to_db`(L1079) + `_record_metric`(L1102)의 `datetime.now().isoformat()` → `datetime.now(UTC).isoformat()`. naive ISO 문자열이 worker handler를 거쳐 `Signal.detected_at`·`SystemMetric.recorded_at` (TIMESTAMPTZ) 컬럼에 명시 set되면서 `validate_timezone_aware` listener에 의해 ValueError로 차단되던 흐름을 해소.
  - tests/test_engine_db_integration.py: 회귀 테스트 2건 추가 — `TestRecordMetric.test_recorded_at_is_timezone_aware`, `TestRecordSignalToDb.test_detected_at_is_timezone_aware`.
- 배경: 2026-05-12 fb7b548에서 도입된 `before_flush` 리스너가 큐 경유 적재 경로의 naive timestamp를 막아 2026-05-12 15:20 UTC 이후 system_metrics·signals 영속화가 16+ 시간 단절. 일일 리포트는 `repository.py:884`를 원인으로 지목했으나 해당 라인은 c44dade에서 이미 정리됨 — 실제 차단 지점은 상류의 큐 적재부.
- 영향: system_metrics·signals 영속화 즉시 복구. 자동 파이프라인 안전 게이트 룰 C(에러)·룰 D(사이클) 트리거 신뢰성 회복. 일일/주간 리포트의 시그널 정확도·signal_performance 분석 데이터 기반 회복.
- 검증 결과: pytest 변경 회귀 테스트 ✅ 2 passed | 전체 410 passed, 5 pre-existing fail (KST 17시대 시간대 의존) + 10 pre-existing errors (SQLite JSONB 호환성) — 모두 본 변경 무관 stash 검증 완료 | ruff src/engine.py + tests ✅ | mypy 변경 라인 에러 없음.

---

## [2026-05-13] 분석 프롬프트의 signals 시간축을 detected_at으로 통일 (v0.2.3, bump 없음)
- 제안서: docs/proposals/2026-05-12_signals-time-axis-unify.md
- 카테고리: docs
- 변경 파일:
  - docs/prompts/_common_rules.md: 시간 필터 정책 한 줄 추가 — signals는 항상 `detected_at` 사용.
  - docs/prompts/daily_routine.md: signal_performance(L87), rolling_7d_signals(L178) 쿼리의 `created_at` → `detected_at`.
  - docs/prompts/weekly_routine.md: signal_performance(L65) 쿼리의 `created_at` → `detected_at`.
- 영향: 분석 시간축이 비즈니스 이벤트 시점(`detected_at`)으로 일관화. 일자 경계 근처 트랜잭션 지연으로 인한 미세한 일자 누수 차단. 후속 프롬프트 작성 시 혼용 재발 방지.
- 검증 결과: 문서 변경 only, pytest 영향 없음 (record_implementation `--category docs`로 bump 없음).

---

