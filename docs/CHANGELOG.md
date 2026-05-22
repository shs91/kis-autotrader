# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (82건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-05-22] 일일 MDD halt 순손실 가드 — 흑자 구간 조기 halt 제거 (v0.4.2) — 🔴 핫픽스
- 제안서: docs/proposals/2026-05-21_daily-drawdown-peak-denominator-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/risk.py: `record_trade_result`의 MDD 발동 조건에 `self._daily_cumulative_pnl < 0` 순손실 가드 추가. 분모가 '당일 실현이익 피크'라 장 초반 작은 피크 직후 정상 손절 1건만으로 비율이 폭증하던 흑자 구간 오발동 제거.
  - tests/test_strategy/test_risk.py: 신규 `TestDailyDrawdownNetLossGuard` 3종(흑자 무halt 회귀 / 순손실 halt 보존 / 연패 경로 무영향) + 기존 `test_daily_drawdown_halt_returns_specific_code`를 순손실 시나리오로 갱신.
  - tests/test_engine_buy_gate_metric.py: 구 동작(흑자 halt) 의존 케이스를 순손실 시나리오로 갱신.
- 배경: 2026-05-21 09:11 익절 +39,440(피크) → 09:21 손절 -24,300 → 누적 +15,140(흑자)인데 피크 대비 회수폭 61.6% ≥ 5%로 `MAX_DAILY_DRAWDOWN` halt 발동, 장 마감까지 5시간 35분 전면 중단(66사이클, 평소 500~700 대비 91% 급감). trip 값 61.6% > 허용 상한 15%라 param 튜닝으로 막을 수 없는 분모 정의(로직) 결함. 사용자가 안 (a) 순손실 가드 채택(고위험 리스크 게이트 완화 → 수동 승인 후 PR #37).
- 영향: 일일 MDD halt는 당일 누적이 순손실(<0)일 때만 발동(일일 '손실' 한도 취지 일치). 흑자 구간 '첫 익절 → 손절' 오발동 제거로 정상 매매 지속(추정 600~700사이클 정상화). 흑자 구간 give-back 보호는 per-position 트레일링 스톱이 담당.
- 검증 결과: pytest test_risk 53 + 전체 908 passed (flaky test_health_endpoint 1건 deselect — 실DB 신선도 의존, 무관) | ruff ✅ | mypy ✅.
- 비고: 운영자 액션 — 전략 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요. 동반 권장(별도): halt 발동 시 system_metrics(HALT) 1회 적재로 모니터링 가시성 확보.

---

## [2026-05-22] Stop 훅 검증 게이트를 in-session verifier와 실제 연결 — 충족불가 게이트의 헛돌이 루프 제거 (v0.4.1)
- 카테고리: bug_fix
- 변경 파일:
  - scripts/harness/run_verifier.py: `HARNESS_CYCLE_ARTIFACTS_PATH`가 설정되면 Stop 훅이 읽는 표준 산출물 파일(`cycle_artifacts.json`, top-level pytest/mypy/ruff 키)을 함께 기록. in-session verifier agent가 step 5에서 실행하면 게이트 자동 충족. env 미설정(수동 실행)이면 미기록.
  - src/harness/cycle/orchestrator.py: 위 env를 `claude` 서브프로세스에 주입 + 사이클 시작 시 이전 사이클 산출물 제거(거짓 통과 방지).
  - scripts/claude-hooks/run_hook.py: 페이로드→파일 폴백 + 재진입 가드(`stop_hook_active`). 첫 종료 시도엔 차단(검증 유도), 재진입에도 부재면 통과+경고로 무한루프 차단. 최종 강제력은 후처리 verifier 재시작 게이트가 유지.
  - scripts/auto_implement_prompt_v2.txt: step 5 verifier 실행이 게이트를 자동 충족함을 명시(코디네이터의 수동 파일 작성 방지).
  - tests: test_hook_wrapper(재진입 가드/첫 시도 차단/격리 보강), test_verifier_cli(canonical 쓰기·스킵), test_cycle_orchestrator(env 주입·stale 제거) 신규 7종.
- 배경: orchestrator가 `HARNESS_CYCLE_VERIFICATION_REQUIRED=1`로 `claude -p`를 띄우면 Stop 훅이 `verification_artifacts`를 요구하나 Claude Code Stop 이벤트는 이를 절대 싣지 않음. 산출물을 만드는 후처리 verifier는 claude 종료 *후* 실행돼 시점상 게이트 충족 불가 → 매 종료 차단 → headless claude가 강제 재개되어 Claude Code 내부 상한까지 무의미한 턴/토큰/시간 소모(검증 강제는 못 함). 격리 재현 테스트로 headless가 Stop exit 2를 정직히 따라 재진입(loop)함을 실증했고, 호스트 `~/.kis-autotrader/cycle_artifacts.json`에 코디네이터가 수동으로 써넣은 흔적(5/22 17:16)으로 실제 차단 발생을 확증.
- 영향: verifier(쓰기)와 Stop 훅(읽기)이 단일 산출물 경로를 공유해 게이트가 의도대로 작동. step 5 verifier 실행만으로 종료 게이트 충족, 재진입 가드로 헛돌이 루프 제거(이전 11분대 사이클 정상화 기대).
- 검증 결과: pytest test_harness 169 passed (신규 7 포함) | ruff 변경 파일 ✅ | mypy 변경 파일 ✅ | E2E 배선 4시나리오 실증(쓰기→읽기 통과 / 첫 시도 차단(2) / 재진입 루프 차단(0+경고)).
- 비고: PR #36 머지. 함께 묶였던 2026-05-21 파이프라인 문서 3건은 `docs/pipeline-artifacts-2026-05-21` 브랜치로 분리(critical drawdown 제안서 (a)/(b) 결정 대기). 하네스 내부 도구 변경이라 서비스 재시작 불요 — 다음 자동구현 cron(월 17:15)부터 적용.

---


