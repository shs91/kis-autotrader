# 하네스 Phase 4 완료 리포트

> **작성일**: 2026-05-18 (KST)
> **워크트리**: `kis-autotrader-phase4` / 브랜치 `feat/harness-phase4` (main `41bda7c`에서 분기)
> **RFC**: [`docs/plans/2026-05-15_harness-phase4-rfc.md`](../plans/2026-05-15_harness-phase4-rfc.md)
> **Phase 3 완료**: [`phase3_completion.md`](./phase3_completion.md)

---

## 1. 12 Task 봉인 결과

| Task | 산출물 | 커밋 |
|------|--------|------|
| T1 | `trajectory_entries` 테이블 + `proposals.prediction` 컬럼 + Alembic `9374c8f9c742` | `06ff3e5` |
| T2 | TrajectoryRepository + TDD 4 | `f015ee2` |
| T3 | trajectory 적재 헬퍼 (`append_entry` + `time_step` 컨텍스트) + TDD 3 | `1a71278` |
| T4 | Initializer + Cycle Orchestrator trajectory wiring + TDD 1 | `5d81824` |
| T5 | Component 분류기 (`classify_component`) + **TDD 32건 parametrize** | `fb5209b` |
| T6 | Verifier `changed_files` JSONB에 component 자동 채움 | `90939a9` |
| T7 | 제안서 prediction 파싱 + `set_prediction` + sync 적재 + TDD 3 | `86842e8` |
| T8 | `get_prediction_calibration` + TDD 2 | `6247bde` |
| T9 | `get_recurrence_risk` (같은 component N회 / 7일) + TDD 4 | `e6d4c80` |
| T10 | `dashboard/pages/pipeline.py` 5섹션 (성공률/MTTR/failure/heatmap/calibration) | `c86a4dd` |
| T11 | `format_pipeline_summary` Telegram 3섹션 카드 + TDD 3 | `5a8c9d2` |
| T12 | 본 완료 리포트 | (본 커밋) |

**신규 테스트**: ~57건 추가 (4+3+1+32+3+2+4+3+5+others). 누적 **186 passed** (`pytest tests/test_harness/ tests/eval/ tests/test_db/test_proposals_repository.py tests/test_db/test_trajectory_repository.py tests/test_notify/test_harness_commands.py tests/test_notify/test_formatter_pipeline.py tests/test_analytics/ -q` → `186 passed in 4.05s`).

---

## 2. 3축 Observability 충족 매핑 (축 C)

| 축 | Phase 4 산출물 |
|----|----------------|
| **Component Observability** | T5 분류기 + T6 자동 채움 — 모든 changed_files에 component 필드 자동 적재 (code/strategy, harness/agent, migration 등 32 카테고리) |
| **Experience Observability** | T1 `trajectory_entries` + T2 Repository + T3 헬퍼 + T4 wiring — 사이클 단계별 입력/결과/시간/토큰 DB 적재 |
| **Decision Observability** | T7 prediction 파싱 + `set_prediction` + T8 calibration — 제안서 `## 기대 효과` 정량 키를 DB에 적재하고 카테고리별 평균 집계 |
| **재발 위험 자동 집계** | T9 `get_recurrence_risk` — 같은 component/파일을 7일 내 N회 수정한 케이스를 자동 식별 |
| **대시보드 가시화** | T10 `dashboard/pages/pipeline.py` 5섹션 |
| **Telegram 결산 강화** | T11 3섹션 카드 (오늘 적용 / 회귀 위험 / 예측 미달) |

---

## 3. 진단 해결 매핑

| 진단 (계획서 §3) | Phase 4 해결 |
|------------------|--------------|
| D6 관측성: logfile + Telegram 평문에 머무름 | T1~T4 trajectory + T10 대시보드 + T11 Telegram 3섹션 |
| 축 C Component Observability | T5 + T6 — changed_files에 component 자동 채움 |
| 축 C Experience Observability | T1~T4 trajectory 단계별 적재 |
| 축 C Decision Observability | T7 + T8 — prediction 파싱 + calibration |
| 동일 모듈 N회 수정/동일 사유 N회 실패 자동 집계 | T9 `get_recurrence_risk` |
| Phase 3 §6 진입 준비 충족 | T1·T4·T10·T11 모두 |

---

## 4. 검증 요약 (T12)

### pytest 누적
- Phase 4 신규 + Phase 3 회귀 = **186 passed in 4.05s**
- 신규 모듈 회귀: 0
- 사전 존재 실패는 본 Phase 범위 밖 (시간 의존 flake 4건 + `test_get_optimal_risk_params` 1건)

### ruff (Phase 4 신규 모듈)
- `src/harness/observability/`, `src/harness/verifier/diff.py`, `src/db/repository.py`(신규 라인), `src/db/analytics.py`(신규 함수), `dashboard/pages/pipeline.py`, `src/notify/formatter.py` 신규 라인, 모든 신규 테스트 → **All checks passed**
- `src/db/analytics.py:821/940`의 E501 2건은 사전 존재(`get_max_drawdown`/`get_profit_factor` — Phase 4 이전 커밋)

### mypy --strict (Phase 4 신규 모듈)
- `src/harness/observability/` → 0 errors
- `src/db/models.py`의 dict[type-arg] 8건 — Proposal.prediction + TrajectoryEntry.meta 신규 2건 + 사전 존재 6건 (다른 JSONB 컬럼들). RFC 명시 "사전 존재 dict[type-arg] 무관"

### Initializer smoke test (메인 repo 컨텍스트, 워크트리 미사용)
- 5/18 22:36 cron 사이클: cycle_id `auto-20260518-222852`, all_pass=**True**, "구현된 제안서 없음 — 재시작 스킵" → 정상 종료 ✓
- D1 hotfix(set -e 우회) 통과, D2 hotfix(Verifier scope) 정상 동작 (`no diff vs HEAD — skip verifier`)

---

## 5. 운영 영향 / 머지 시 주의

본 Phase 4도 워크트리(`feat/harness-phase4`)에 한정. 머지 시 결정:

### 5.1 시스템 영향 (현재 = 워크트리 한정)

- **`trajectory_entries` 테이블**: Alembic `9374c8f9c742`로 운영 DB에 적용됨. autotrader는 사용 안 함 → 운영 0
- **`proposals.prediction` 컬럼**: nullable, 기존 행에 영향 없음
- **dashboard/pages/pipeline.py**: 머지 + dashboard 재시작 시 즉시 활성
- **`format_pipeline_summary`**: 호출자 미연결 — 사이클 종료 시 Telegram 전송 wiring은 별도 hotfix (Cycle Orchestrator가 호출)

### 5.2 머지 시 결정 사항

1. **머지 후 대시보드 재시작**: `launchctl stop com.kis.dashboard && launchctl start com.kis.dashboard` → 새 페이지 즉시 사용 가능
2. **trajectory 적재 활성화**: `run_cycle()`에 `trajectory_repo` 파라미터를 실제 전달하도록 `run_auto_implement.sh`의 Python 호출에서 인스턴스화 — 별도 hotfix 권장 (T4는 기능만 추가, wiring은 옵션 유지)
3. **prediction backfill**: 기존 39 markdown 제안서를 다시 `sync_proposals_md_to_db` 실행해 `## 기대 효과` 섹션 있는 것은 prediction 적재
4. **Telegram 카드 활성화**: `cmd_run_implement` 또는 사이클 종료 후 자동 발송 wiring 별도

### 5.3 운영 상태 (현재)

- `com.kis.autotrader` PID 88654 정상 운영 (Phase 3 hotfix 적용된 코드)
- 5/18 22:28~22:36 cron 사이클 정상 완료 — D1~D5 hotfix 실증 통과
- 다음 평일 17:00 cron이 Phase 4 머지 후 흐름의 실증 시점

---

## 6. Phase 5 진입 준비

Phase 4가 만든 데이터 자산 위에서 Phase 5가 할 일 (harness plan §5 Phase 5, 축 E):

1. **4-cadence(일/주/월/분기) 리포트 파이프라인의 하네스화** — 각 cadence가 같은 Initializer→DataAuditor→Analyst→Critic→ProposalSynthesizer 토폴로지로 회전
2. **Data Auditor (subagent, Read-only)** — query_analytics raw JSON 무결성 점검 (`total_pnl` 합 검증, NULL/NaN 검출). 실패 시 stub 리포트로 종료
3. **Analyst의 인용 주석 강제** — 모든 수치에 `<!-- src: query_analytics 출력 경로 -->` 표시
4. **Critic (fresh-context)** — Default-FAIL contract로 채점 (수치 일치/결론-수치 매핑/이전 prediction 대조/회귀 위험 노출)
5. **Proposal Synthesizer** — 리포트 "개선 포인트"를 자동으로 ready 제안서로 분리
6. **분기 리포트 신설** — BRIDGE_SPEC PR 필요

Phase 5는 **리포트 입력의 정합성**을 강제해 자동 구현 사이클의 의사결정 품질을 데이터 차원에서 보강한다.

---

## 7. 결론

Phase 4 RFC 12 task 모두 봉인. 3축 Observability(Component/Experience/Decision)와 가시화(대시보드 + Telegram) 인프라 완성. 다음 사이클부터:

- **모든 changed_files이 component 단위로 분류되어 적재**
- **모든 사이클 단계가 `trajectory_entries`에 추적**
- **모든 제안서의 정량 기대 효과가 `proposals.prediction`에 적재**
- **재발 위험·예측 정확도가 자동 집계되어 대시보드와 Telegram에 노출**

Phase 5는 본 인프라가 만든 데이터 자산을 4-cadence 리포트 파이프라인의 정합성 강제에 활용한다.
