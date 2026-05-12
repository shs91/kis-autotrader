# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (74건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-12] TIMESTAMPTZ에 naive datetime 저장 버그 수정 + listener + 스크리너 매매시간 가드 (v0.2.1)
- 제안서: docs/proposals/2026-05-12_timestamp-naive-to-aware-utc.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `datetime.now()` 2곳 `datetime.now(UTC)`로 교체 + UTC import.
  - src/worker/screener.py: `_is_trading_window()` 가드 추가 (휴장일/매매시간 외 스킵), `datetime.now()` → `datetime.now(UTC)`.
  - src/db/session.py: `before_flush` 리스너로 TIMESTAMPTZ 컬럼에 명시 set된 naive datetime 거부.
  - tests/test_db/test_timezone_validation.py: 신규 3 케이스 (naive 거부, aware UTC/KST 허용).
  - tests/test_worker/test_screener.py: 가드 우회 mock 추가.
- 데이터 처리: `screening_results` 전수 TRUNCATE (24/7 작동 누적 + 시간 어긋남 row 폐기). 손상 trades/signals는 사용자가 별도 백필 완료.
- 영향: 신규 row의 timestamp 절대 시각 정확. 일자 경계 misclassification 해소. 휴장일 INSERT 차단. 회귀 시 ValueError 즉시 발생.
- 검증 결과: pytest 461 passed (5 pre-existing) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-05-12] 자동 SemVer 버저닝 시스템 도입 (v0.1.0 → v0.2.0)
- 카테고리: feature
- 변경 파일:
  - src/__version__.py: 단일 버전 출처 신설.
  - src/utils/versioning.py: 카테고리→bump 매핑, SemVer 파싱/bump, `__version__.py`+`pyproject.toml` 동시 갱신.
  - scripts/record_implementation.py: 검증 통과 시점 자동 bump + `VERSION=v0.x.x` stdout 출력 (`--no-bump` 플래그 지원).
  - src/notify/formatter.py & telegram.py: 일일 결산 헤더에 `[vX.Y.Z]` + 당일 bump 내역 섹션 자동 노출.
  - src/db/models.py + src/db/repository.py + alembic/versions/edb0690663bb_*.py: `implementation_logs.version` 컬럼 추가.
  - scripts/auto_implement_prompt.txt & auto_heal_prompt.txt: `git tag -a $VERSION` 단계 명시.
  - docs/BRIDGE_SPEC.md: 자동 버저닝 규칙 명문화.
  - tests/test_versioning.py + tests/test_notify/test_formatter.py: 단위 테스트 31건 추가.
- 영향: 검증 통과 시점에만 annotated tag 부여 → 알려진 정상 지점 목록 확보. 결산 헤더에 버전 노출. 롤백은 `git checkout v0.x.y && launchctl restart`.
- 검증 결과: pytest ✅ (468 passed, 1 pre-existing analytics fail) | mypy: pre-existing 에러만 | ruff (신규 파일) ✅ | end-to-end: 자체 변경 기록 시 0.1.0 → 0.2.0 (minor bump) 정상 동작.

---

## [2026-05-12] 스크리닝 종목명 stocks 테이블 자동 등록 — 코드/알림/캘린더 표시 정상화
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_screen_stocks`에서 screening_results의 (code, name) 페어를 수집해 `_upsert_stock_names` 호출 — stocks 테이블에 사전 등록되어 `_resolve_stock_name` 폴백이 정상 동작. 현재가 API의 `HTS_KOR_ISNM`이 비어있는 종목도 종목명으로 표시됨.
- 백필: screening_results 최근 14일치에서 stocks 테이블로 일괄 upsert (신규 338, 보정 4).
- 영향: DB(trades/signals)·Telegram 알림·Google Calendar 등록 시 종목 코드 대신 종목명 표시. 신규 매매부터 적용 (기존 trades/signals 행은 이력 보존).
- 검증 결과: pytest test_engine_db_integration.py ✅ (24 passed) | mypy: pre-existing 에러만 | ruff ✅

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

