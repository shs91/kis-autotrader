# Phase 0 Baseline — 하네스 엔지니어링 측정 베이스라인

> **작성일**: 2026-05-14 (KST)
> **워크트리**: `kis-autotrader-harness` / 브랜치 `feat/harness-phase1`
> **참조 계획**: [`docs/plans/2026-05-14_harness-engineering-improvement.md`](../plans/2026-05-14_harness-engineering-improvement.md)
> **JSON 원본**: [`phase0_baseline.json`](./phase0_baseline.json)

Phase 0의 두 가지 작업(ruff 룰셋 활성화 + 사이클 KPI baseline 측정)을 통해 산출된 기준선을 기록한다. 이후 Phase 1~5의 성과는 본 문서의 수치를 기준으로 측정한다.

---

## 1. ruff 룰셋 변경 — DTZ / B / S 추가

### 1.1 변경 내역 (`pyproject.toml`)

```diff
 [tool.ruff.lint]
-select = ["E", "F", "I", "N", "W", "UP"]
+select = ["E", "F", "I", "N", "W", "UP", "DTZ", "B", "S"]
+
+[tool.ruff.lint.per-file-ignores]
+(파일별 기존 위반 grandfather — 1.3절 참조)
```

### 1.2 룰셋 의도

| 룰 | 의미 | 도입 근거 |
|----|------|----------|
| `DTZ` | naive datetime 사용 차단 | 계획서 D7. naive datetime 버그가 0.2.1→0.2.3→0.2.4 연속 재발 (직전 7일 내 3회) |
| `B` | bugbear (zip strict 누락 등 일반적 버그 패턴) | 함수 인자 mutable default, zip 길이 불일치 등 |
| `S` | 보안 (try-except-pass, hardcoded bind 등) | 향후 리스크 표면 측정 |

### 1.3 Baseline 위반 분포 (총 63건, per-file-ignores로 grandfather)

| 파일 | grandfather 룰 | 건수 |
|------|---------------|-----|
| `src/db/analytics.py` | DTZ001, DTZ005 | 25 |
| `src/engine.py` | DTZ005, DTZ011, S110 | 13 |
| `src/api/auth.py` | DTZ005, DTZ007 | 5 |
| `src/scheduler/jobs.py` | DTZ005, DTZ011 | 4 |
| `src/db/repository.py` | DTZ001, DTZ011 | 4 |
| `src/strategy/ensemble.py` | B905 | 2 |
| `src/api/rate_limiter.py` | S110, DTZ011 | 2 |
| `src/api/quote.py` | DTZ007, DTZ011 | 2 |
| `src/api/health.py` | S104, DTZ005 | 2 |
| 기타 (account/holidays/screener/risk) | DTZ005/DTZ011 | 4 |
| **합계** | | **63** |

> **신규 코드는 동일 파일에서도 새 위반을 추가할 수 있다는 한계가 있다.** 진정한 차단을 원하면 후속 Phase에서 per-file-ignores를 라인별 `# noqa` 마커로 마이그레이션해야 한다. Phase 0 범위에서는 grandfather + 새 파일 차단까지를 목표로 한다.

### 1.4 검증

```bash
.venv/bin/ruff check src/ --select DTZ,B,S
# → Found 0 errors (per-file-ignores 적용 후)
```

기존부터 존재하는 16건의 pre-existing 위반(E501 12, F401 2, I001 1, UP035 1)은 본 Phase의 범위가 아니며 별도 cleanup 제안서로 분리한다.

---

## 2. 자동 구현 사이클 KPI Baseline (최근 90일)

스크립트: [`scripts/harness/baseline_kpis.py`](../../scripts/harness/baseline_kpis.py)
실행: `PYTHONPATH=. .venv/bin/python -m scripts.harness.baseline_kpis --days 90`

### 2.1 제안서 상태 (`docs/proposals/*.md` 파싱)

| 항목 | 값 |
|------|----|
| 총 제안서 수 | 37 |
| `implemented` | 36 |
| `unknown` (메타 파싱 불가) | 1 |
| `failed` | **0** |
| `skipped` | **0** |
| 명목 성공률 | 100.0% (분모 36) |

**해석**: 성공률 100%는 D6 진단(*실패 traces 부재*)을 직접 증명한다. **현재 시스템은 실패한 시도를 markdown에서도 DB에서도 보존하지 않는다.** Phase 1의 `proposals` 테이블 신설 시 모든 상태 전이(`draft → ready → in_flight → implemented/failed/skipped`)를 적재해야 KPI가 의미를 갖는다.

### 2.2 제안서 카테고리 분포

| 카테고리 | 건수 | 비율 |
|---------|-----|------|
| bug_fix | 20 | 54% |
| param_tuning | 8 | 22% |
| refactor | 4 | 11% |
| performance | 3 | 8% |
| docs | 1 | 3% |
| unknown | 1 | 3% |

### 2.3 `implementation_logs` 분포

| 항목 | 값 |
|------|----|
| 90일 구현 건수 | 77 |
| 활성일 수 | 28 |
| 활성일당 평균 구현 | 2.75 |
| 제안서 수와의 차이 | **77 − 37 = 40** — 사이클당 평균 2.08건 부가 commit이 implementation_logs에 별도 적재됨 (자동 핫픽스, 수동 fix 등) |

카테고리 분포 (DB 기준):

| 카테고리 | 건수 |
|---------|-----|
| bug_fix | 31 |
| enhancement | 27 |
| param_tuning | 6 |
| refactor | 5 |
| performance | 3 |
| feature | 2 |
| docs | 2 |
| config | 1 |

### 2.4 재발률 — 측정 불가 (관측성 결여 확인)

| 항목 | 값 |
|------|----|
| 7일 내 동일 파일 재수정 | 0 / 0 = N/A |
| `changed_files` JSONB가 채워진 로그 | 0 |

**해석**: `record_implementation.py`가 `changed_files`를 채우지 않거나, 채우더라도 일관된 스키마가 아니라서 파싱에 실패함. 이건 plan D6의 *관측성 부재* 의 또 다른 증거이며, Phase 1에서 `record_implementation.py`의 `changed_files` 적재 표준화(JSON Schema 정의)가 필수.

### 2.5 재발 패턴 (정성)

90일 trail 중 직전 7일 구현 trace:

- 2026-05-12 `0.2.1` — naive datetime TIMESTAMPTZ 버그
- 2026-05-13 `0.2.3` — `repository.py`의 `datetime.utcnow()` 제거
- 2026-05-13 `0.2.3` — analytics 프롬프트 signals 시간축 통일
- 2026-05-13 `0.2.4` — engine.py 큐 적재 naive timestamp 차단 버그

**3일에 걸쳐 4건의 datetime 관련 수정**. DTZ 룰셋 도입의 정당성을 통계 기준으로도 보강한다.

### 2.6 토큰 사용량

현재 미적재. Phase 3의 trajectory 테이블 도입 시 사이클별 토큰 사용량을 component(initializer/validator/implementer/verifier) 단위로 적재할 예정.

---

## 3. pre-commit hook — 활성화 보류 (수동 결정)

스크립트: [`scripts/git-hooks/pre-commit`](../../scripts/git-hooks/pre-commit)

`--select DTZ,B,S`로 좁힌 가벼운 hook이며, 신규 코드의 DTZ/B/S 위반만 차단한다 (기존 16건의 E501 등은 무시).

### 3.1 활성화 보류 사유

worktree와 main repo가 `.git/hooks/`를 공유하기 때문에 hook 설치는 **운영 중인 autotrader 프로세스의 커밋 환경에도 영향**을 준다. Phase 0 산출물은 “추적되는 스크립트”로 정의하고, 실제 git wiring은 사용자가 머지 시점에 결정하도록 보류.

### 3.2 활성화 명령 (사용자 수동)

```bash
# 메인 repo 루트에서
ln -sf "$(pwd)/scripts/git-hooks/pre-commit" .git/hooks/pre-commit
chmod +x scripts/git-hooks/pre-commit  # already executable

# 또는 디렉토리 단위 설정 (git config 변경 — 사용자 결정)
git config core.hooksPath scripts/git-hooks
```

### 3.3 동작 확인 방법

```bash
# 임의로 naive datetime 사용 코드 스테이징
git add -p src/notify/telegram.py  # datetime.now() 가 들어간 변경분
git commit -m "test"
# → [pre-commit] BLOCKED: Phase 0 신규 룰(DTZ/B/S) 위반.
```

---

## 4. Phase 1 진입 게이트 (목표값)

본 Phase 0 baseline을 기준으로, Phase 1 종료 시점에서 다음 수치를 달성해야 한다.

| 지표 | Phase 0 baseline | Phase 1 종료 목표 |
|------|-----------------|------------------|
| DTZ/B/S 신규 위반 (CI 검사) | n/a | 0 (pre-commit + CI gate) |
| `proposals` 상태 머신 sole source of truth | markdown 텍스트 | `proposals` DB 테이블 |
| `failed` 상태가 DB에 적재되는 비율 | 0% | 100% |
| `changed_files` JSONB 적재된 implementation_logs | 0 / 77 (0%) | 100% (신규 사이클부터) |
| 수동 트리거 표준 채널 | 없음 | Telegram 3개 명령 + CLI 1개 |
| 사이클 시작 시 환경 점검 (`claude-progress.json`) | 없음 | Initializer가 매 사이클 생성 |

이후 Phase 2(Verifier+골든셋), Phase 3(5계층 ADK), Phase 4(3축 Observability), Phase 5(리포트 cadence)의 개별 진입 게이트는 각 Phase RFC에서 별도 정의.

---

## 5. 작업 정리 메모

| 항목 | 위치 |
|------|------|
| 워크트리 | `/Users/songhansu/IdeaProjects/kis-autotrader-harness` (`feat/harness-phase1`) |
| 메인 repo 영향 | 없음 (코드 편집은 worktree에 격리, DB·plist 변경 없음) |
| .env 공유 | worktree 내 `.env` → 메인의 `.env` 심볼릭 링크 |
| autoimplement plist | unload하지 않음 (Phase 0은 파이프라인 동작 변경이 없으므로) |

Phase 1 진입 시 `com.kis.autoimplement.plist`를 `launchctl unload`로 일시 중단할 것. 이유는 Phase 1의 `proposals` 테이블 마이그레이션이 메인 repo의 자동 사이클과 직렬화되어야 하기 때문.
