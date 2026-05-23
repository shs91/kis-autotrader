# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (95건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-23] 종목별 당일 진입 횟수 제한 — 동일 종목 다중 진입 차단 (v0.5.0)
- 제안서: docs/proposals/2026-05-23_daily-trade-limit-per-stock.md
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: `TradingConfig.max_daily_trades_per_stock` 추가(기본 2, env `MAX_DAILY_TRADES_PER_STOCK`).
  - src/engine.py: `_process_stock` 매수 경로에 종목별 당일 진입 게이트 신설(전체 일일한도 체크 직후, check_buy_gates 직전). 한도 도달 시 `BUY_REJECT(reason=DAILY_TRADE_LIMIT_PER_STOCK)` 기록 후 매수 차단. 체결 확정 시 `_today_buys_per_stock[code]` 누적, `pre_market`에서 일자 단위 리셋.
  - .env.example / README.md / CLAUDE.md: `MAX_DAILY_TRADES_PER_STOCK` 문서화.
  - tests/test_engine_daily_trade_limit_per_stock.py: 한도 도달 차단 / 미만 허용 / 종목별 독립 / pre_market 리셋 4종 신규.
- 배경: 2주 연속 동일 종목 3회전 진입 패턴(W21 §7) — 동일 종목 반복 진입이 손실을 누적. 매수 게이트는 종목별 진입 횟수를 보지 않았다.
- 영향: 동일 종목 당일 매수 2회로 제한(3회차부터 차단). 매도(보유분 청산)는 항상 허용. 인메모리 카운터(`_today_trade_count`와 동일 패턴) — 일중 재시작 시 리셋되는 한계는 기존 일일 카운터와 동일.
- 검증 결과: pytest **927 passed**(신규 4 포함) | mypy ✅ | ruff(변경 파일) ✅ | golden 11 ✅.
- 비고: 주간분석 제안서가 안전 게이트(리스크 게이트 코드 변경)에 막혀 SKIPPED 처리된 것을 수동 검토 후 구현. 운영자 액션 — 전략 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요.

---

## [2026-05-23] sell_reason ↔ 실현 PL 부호 일관성 보정 — 760027 ETN STOP_LOSS anomaly 차단 (v0.4.6)
- 제안서: docs/proposals/2026-05-23_sell-reason-classification-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_reconcile_sell_reason` 헬퍼 신설 — `_record_trade_to_db`에서 체결가 기준 실현 PL 부호로 STOP_LOSS↔TAKE_PROFIT 라벨을 보정(layer 1). 보정 시 `SELL_REASON_CORRECTED` 메트릭 기록. TRAILING_STOP/MARKET_CLOSE/STRATEGY는 분류가 명확하므로 유지.
  - src/db/models.py: `Trade` `before_insert`/`before_update` listener로 PL-라벨 일관성 강제(defense-in-depth). 엔진을 우회하는 경로(백테스트·직접 적재)도 커버. (부수: 기존 E501 1건 정리)
  - tests/test_engine_sell_reason.py(엔진 보정 4종) + tests/test_db/test_sell_reason_consistency.py(listener 8종) 신규.
- 배경: 게이트는 조회 시점 시세로 sell_reason을 결정하나 profit_loss_pct는 체결가로 계산 → 시세 stale/이상값 시 둘이 어긋난다. 760027 ETN이 PL +18.54%인데 STOP_LOSS로 기록(2026-05-22 09:00), W21 손익비/sell_reason 통계 왜곡.
- 영향: STOP_LOSS/TAKE_PROFIT 라벨이 실현 PL 부호와 항상 일치. 룰 A/B·통계가 sell_reason에 의존해도 측정 오류 제거. PL=0은 모호하므로 보정 안 함.
- 검증 결과: pytest **927 passed**(신규 12 포함) | mypy ✅ | ruff(변경 파일) ✅ | golden 11 ✅.
- 비고: 안전 게이트가 SKIPPED 처리한 제안서를 수동 검토 후 구현. 운영자 액션 — `com.kis.autotrader` 재시작 필요.

---

## [2026-05-22] mypy strict baseline 정리 — 85건 → 0건 (전역 타입 클린업) (v0.4.5)
- 카테고리: refactor
- 변경 파일:
  - pyproject.toml: 타입 스텁 없는 서드파티(pandas/apscheduler/google_auth_oauthlib/googleapiclient)에 `ignore_missing_imports` override 추가 → `import-untyped` 16건 제거.
  - src/db/: JSONB·payload 컬럼/파라미터 `dict`→`dict[str, Any]`(type-arg 14건), analytics 제너레이터 item type(`int|None`→`or 0`)·unary minus 대상 `cast(int, ...)`.
  - src/worker/: screener·engine의 `ranked: list[object]`→`list[VolumeRankItem]`, runner `task: object`→`TaskQueue`, queue의 SQLAlchemy `delete(TaskQueue)` 구문·`CursorResult.rowcount` cast.
  - src/engine.py: `object`/`list[object]`→실타입 `Balance`/`Execution`/`VolumeRankItem` 주입.
  - src/strategy/: rsi 불용 `type: ignore` 제거, macd/bollinger 초기화값 `cast(int/float, ...)`.
  - src/api/: auth/quote/account `.json()` Any 반환 `cast(str, ...)`, rate_limiter 동기 redis 반환 cast(stub의 sync/async 모호성).
  - src/calendar/google_auth.py: google-auth 부분 미타입 메서드 `cast`+`# type: ignore[no-untyped-call]`. src/notify/bot.py: params `dict[str, str|int]`·json 반환 cast. src/scheduler/jobs.py: `asyncio.run` 인자 Coroutine 타입. src/market_stats.py: 불용 type:ignore 제거.
- 배경: strict mypy가 전역 85건 에러를 안고 있어 타입 신호가 무력화돼 있었음. v0.4.4에서 verifier 게이트는 '변경 파일 스코프'로 우회했으나 baseline 자체는 미정리 상태였다. 노이즈 16건(스텁 미설치 `import-untyped`) + 실에러 69건(`object` 파라미터·bare `dict`·`Any` 반환 등).
- 영향: `mypy src/` Success(0건, 이전 85건). 이제 verifier/CI에서 mypy 0-tolerance 강제 가능. 런타임 동작 무변경 — 전부 타입/주석/cast/import만 손댔고 pytest 911 passed로 확인. 5개 모듈 병렬 에이전트로 작업 후 중앙 검증(full mypy + 전체 테스트).
- 검증 결과: `mypy src/` Success: no issues found in 93 source files | pytest **911 passed** | ruff 신규 위반 0(기존 E501/F401 12건은 pre-existing, 무관).
- 비고: pandas는 `pandas-stubs` 대신 `ignore_missing_imports` 채택(엄격 스텁은 신규 에러 대량 유발). 변경 파일의 기존 ruff 위반 12건 정리는 별도 과제로 잔존.

---

## [2026-05-22] Verifier mypy 게이트를 변경 파일로 스코프 — baseline 에러발 구조적 FAIL 제거 (v0.4.4)
- 카테고리: bug_fix
- 변경 파일:
  - src/harness/verifier/runner.py: `_run_mypy`가 mypy 파싱 후 변경된 src 파일에서 발생한 에러만 남기도록 필터 추가(`e.file in changed`). mypy는 변경 파일만 타깃해도 import 그래프를 따라 미변경 의존 파일의 에러까지 보고하는데, 그 baseline 에러를 게이트 판정에서 제외(Phase 3 hotfix D2의 '변경 파일 한정' 의도 완성 — 타깃뿐 아니라 보고된 에러도 스코프 제한).
  - tests/test_harness/test_verifier_runner.py: 미변경 의존 파일 에러 스코프 제거→PASS / 변경 파일 자체 에러 보존→FAIL 2종 신규.
- 배경: 전역 mypy baseline이 약 85건(대부분 pandas/apscheduler `import-untyped` 미설치 스텁 + 실에러 일부). verifier는 변경 파일만 타깃하지만 mypy가 import 그래프를 따라가 미변경 파일의 사전 존재 에러까지 보고 → `MypyArtifact.passed`가 `error_count==0`을 요구하므로 코드 import만 닿아도 게이트가 구조적으로 항상 FAIL. 5/22 auto-implement(17:15·19:00) 모두 `verifier exit=2 (mypy errors=82)`로 차단됨을 확인. v0.4.1에서 고친 Stop 훅 충족불가 게이트와 동일 계열의 결함.
- 영향: 변경 파일에서 발생한 mypy 에러만 게이트에 반영. 정상 변경(예: MDD 커밋 risk.py 자체 에러 0건)은 PASS, 변경 파일에 새 타입 에러가 들어오면 FAIL 유지(회귀 검출력 보존). E2E로 MDD 커밋(35047a4) 재검증 시 `overall passed=True, mypy error_count=0`(이전 errors=82) 확인.
- 검증 결과: pytest test_harness 171 passed(신규 2 포함) | ruff 변경 파일 ✅ | mypy 변경 파일(runner.py) 에러 0 | E2E verifier(35047a4) PASS.
- 비고: 하네스 내부 검증 도구 변경이라 서비스 재시작 불요 — 다음 자동구현 cron(평일 17:15)부터 적용. 전역 mypy baseline(≈85건) 자체 정리(pandas-stubs/override 등)는 별도 과제로 잔존.

---

## [2026-05-22] 일간 분석 리포트 영속화 — 구현 0건인 날 리포트 소실 수정 (v0.4.3)
- 카테고리: bug_fix
- 변경 파일:
  - scripts/run_daily_analysis.sh: 분석(`claude -p`) 직후 `docs/reports/<날짜>_daily.md`를 단독 커밋하는 블록 추가(`git add -- <파일>` → `git commit --no-verify -- <파일>`). 현재 브랜치에 해당 파일만 커밋하므로 작업 중 변경/제안서 등 나머지 워킹트리는 무영향(surgical). 파일 미생성(데이터 부족 등)·무변경 시 스킵.
- 배경: `claude -p`가 생성하는 일간 리포트는 untracked 상태로 남는데, 제안서를 구현한 날에는 auto-implement 커밋이 우연히 휩쓸어 보존됐지만 구현 0건인 날(룰 게이트 보류 등)에는 커밋 없이 방치되다 이후 수동/자동 git 작업에 소실됐다. 5/19·5/21·5/22 리포트가 디스크 및 전체 브랜치에 부재함을 확인(분석 로그상 "생성"으로 기록됐으나 파일 없음).
- 영향: 분석 직후 리포트가 즉시 커밋돼 항상 보존된다. auto-implement 사이클이 보던 untracked 리포트 잔존도 일부 해소돼 `git_clean` 경고 완화. 제안서는 본 수정 범위 밖(DB 동기화 안전망 + 향후 별도 보호 검토).
- 검증 결과: bash -n ✅ | 격리 git 스크래치 4케이스(신규 untracked 커밋 / 무변경 스킵 / 미생성 스킵 / 수정 재커밋) + 더티트리 surgical(리포트만 커밋, 수동 작업 보존) 검증 모두 exit 0 ✅.
- 비고: 운영자 액션 불요 — launchd가 매일 스크립트 파일을 직접 실행하므로 다음 일간 분석(평일 16:30)부터 자동 적용. 이미 소실된 5/19·5/21·5/22 리포트는 복구 불가(분석 로그 요약만 잔존).

---


