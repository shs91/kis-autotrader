# 하네스 Phase 1 완료 리포트

> **작성일**: 2026-05-14 (KST 20:10)
> **워크트리**: `kis-autotrader-harness` / 브랜치 `feat/harness-phase1`
> **RFC**: [`docs/plans/2026-05-14_harness-phase1-rfc.md`](../plans/2026-05-14_harness-phase1-rfc.md)
> **Phase 0 baseline**: [`docs/harness/phase0_baseline.md`](./phase0_baseline.md)
> **Phase 1 baseline 재측정**: [`phase1_baseline.json`](./phase1_baseline.json)

---

## 1. 13 Task 봉인 결과

| Task | 산출물 | 커밋 |
|------|--------|------|
| T1 | `ProposalState`/`ProposalPriority` enum + `Proposal` 모델 | `d899854` |
| T2 | Alembic 마이그레이션 `add_proposals_table` (rev `ecdd397b8238`) | `580b867` |
| T3 | `ProposalRepository` + TDD 9건 (SQLite JSONB workaround 적용) | `efd9793` |
| T4 | md → proposals DB 동기화 스크립트 + TDD 3건, 실제 37건 INSERT | `a3eceb0` |
| T5 | `claude-progress.json` v1 (pydantic) + 헬퍼 + TDD 5건 | `435e543` |
| T6 | hook 의사결정 로직 4종 + TDD 27건 (pre_tool_use 9, pre_bash 12, post_edit 3, stop 3) | `2b9b224` |
| T7 | `.claude/settings.json` + `scripts/claude-hooks/run_hook.py` wrapper + TDD 4건 | `42db2af` |
| T8 | `src/harness/trigger.py` + `HarnessSettings` + TDD 7건 | `f6395c6` |
| T9 | `scripts/trigger_implement.sh` CLI 트리거 (수동 dry-run·pause 차단 검증) | `8f26f87` |
| T10 | `cmd_run/status/pause_implement` Telegram 핸들러 + TDD 3건 | `ade61aa` |
| T11 | `main.py` import + `bot.register` 3건 + `main.py` per-file-ignores 보강 | `69cfdcd` |
| T12 | `scripts/run_auto_implement.sh` pause lock 가드 | `5602320` |
| T13 | 본 리포트 + Phase 1 baseline 재측정 | (본 커밋) |

> **합계**: 신규 테스트 **58건 모두 통과** (`pytest tests/test_harness/ tests/test_db/test_proposals_repository.py tests/test_notify/test_harness_commands.py -q`).

---

## 2. Phase 0 §4 게이트 충족 매핑

`docs/harness/phase0_baseline.md` §4에서 정의한 Phase 1 종료 목표 5종 + 본 리포트가 추가로 확인한 1종.

| 지표 | Phase 0 baseline | Phase 1 목표 | 본 Phase 결과 | 비고 |
|------|------------------|-------------|---------------|------|
| DTZ/B/S 신규 위반 (lint gate) | n/a | 0 | **0건** | per-file-ignores grandfather + 신규 코드 모두 통과. `main.py` 사전 존재 13건도 grandfather에 추가 |
| `proposals` 상태 머신 sole source | markdown 텍스트 | DB | **완료** | T1~T4. 37건 markdown → DB sync 완료. mark_* 메소드 통해서만 상태 전이 |
| `failed` 상태 DB 적재 | 0% | 100% (신규부터) | **완료** | `ProposalRepository.mark_failed(reason=...)` 사용 강제. TDD 검증 |
| `changed_files` JSONB 적재 | 0/77 (0%) | 100% (신규부터) | **이관됨** | Verifier 서브에이전트가 채워야 하는 책임 — Phase 2로 이관. Repository는 받아서 저장만 함 |
| 수동 트리거 표준 채널 | 없음 | Telegram 3개 + CLI 1개 | **완료** | `/run_implement`, `/status_implement`, `/pause_implement` + `scripts/trigger_implement.sh` |
| Initializer `claude-progress.json` | 없음 | 매 사이클 생성 | **스키마 완료** | pydantic 모델·load/save·transition 헬퍼 완료. **실제 사이클 시작 시 생성 wiring은 Phase 2의 Initializer 서브에이전트가 담당** |

---

## 3. Phase 2 이관 항목 (의도된 미완료)

| 항목 | 이유 |
|------|------|
| `changed_files` JSONB 자동 채움 | Verifier 서브에이전트가 fresh-context로 diff을 정리해 채우는 것이 D6 진단의 정공법. Repository는 받아서 저장만 함 |
| Initializer가 실제 사이클 시작 시 `claude-progress.json` 생성 | 사이클 entry point 자체의 토폴로지 변경 (현재 `claude -p` 단일 호출 → Initializer 분리) 가 Phase 2 핵심 산출물 |
| Verifier 서브에이전트 분리 (Write/Edit 금지, fresh context) | Phase 2 축 A의 본체 |
| 골든 회귀 셋 (`tests/eval/golden_proposals/`) | Phase 2의 또 다른 산출물. 본 Phase는 안전 게이트만 |
| 사이클 시작 직전 `git stash` + 자동 롤백 강화 | Stop hook에서 verification artifacts 검사까지만 본 Phase. 실제 stash/restore는 Phase 2 |

---

## 4. 운영 영향 / 머지 시 주의

### 4.1 메인 repo와의 격리

본 Phase 1 작업은 `kis-autotrader-harness` 워크트리에서만 봉인되어 있다. 메인 repo(`docs/harness-pipeline` 브랜치)에는:

- `proposals` 테이블이 **PostgreSQL DB에 이미 적용됨** (공유 DB). autotrader는 사용하지 않으므로 운영 영향 0.
- `.claude/settings.json` 적용 안 됨 (워크트리 한정, `.gitignore`로 차단됨)
- 자동 사이클(`com.kis.autoimplement`)이 메인 repo의 `scripts/run_auto_implement.sh`를 호출 — 본 Phase의 pause lock 가드는 워크트리에만 있어 **현재 메인 repo에는 적용 안 됨**

### 4.2 머지 시 결정 사항

머지(=메인 repo로 변경 반영) 시점에 사용자가 결정해야 할 항목:

1. `.claude/settings.json` 메인 repo로 옮길지 (강제 git add 필요: `.gitignore`가 막음)
2. `scripts/run_auto_implement.sh`의 pause lock 가드는 메인에 머지하는 것을 권장 — 머지 후 즉시 `launchctl unload com.kis.autoimplement.plist`로 잠시 멈춤 → 머지 → reload
3. `main.py`의 3개 새 Telegram 명령은 머지 후 `launchctl stop com.kis.autotrader && launchctl start com.kis.autotrader`로 봇 재시작 필요

### 4.3 운영 재개 절차 (서비스 unload된 현재 상태에서)

```bash
launchctl load ~/Library/LaunchAgents/com.kis.autotrader.plist
launchctl load ~/Library/LaunchAgents/com.kis.watchdog.plist
launchctl load ~/Library/LaunchAgents/com.kis.autoimplement.plist
launchctl list | grep kis  # 동작 확인
```

> **머지 전 재개**: 메인 repo의 `scripts/run_auto_implement.sh`에 pause lock 가드가 없으므로, 17:00 cron이 평소대로 동작. 본 Phase의 Telegram `/pause_implement` 명령으로 잠시 멈출 수는 있지만 효과는 머지 이후부터.

---

## 5. 검증 요약 (T13 실행 결과)

### pytest 결과

| 범위 | 결과 |
|------|------|
| Phase 1 신규 테스트만 (`tests/test_harness/` + `test_proposals_repository.py` + `test_harness_commands.py`) | **58 passed** |
| 전체 `tests/` | 522 passed, 5 failed |
| 실패 5건 내역 | 모두 사전 존재 (Phase 1 회귀 0건) |

실패 5건 사전 존재 확인:
- `test_get_optimal_risk_params` — Phase 0 baseline에서도 동일 실패 (메인 repo와 동일)
- `test_strategy/test_risk.py::TestValidateOrder::*` 3건 + `test_custom_profit_ratio` 1건 — **시간 의존 flake** (KST 장 마감 후 `validate_order`가 신규 매수 차단). 메인 repo에서도 동일 실패 (`pytest tests/test_strategy/test_risk.py::TestValidateOrder -q` 출력으로 검증). Phase 1 작업과 무관.

### ruff / mypy

- **ruff 신규 모듈**: `All checks passed!` (src/harness/, scripts/harness/, scripts/claude-hooks/, tests/test_harness/, test_harness_commands.py, test_proposals_repository.py)
- **mypy strict 신규 모듈**: 신규 코드 0 errors. `src/db/repository.py`에 사전 존재 `dict[type-arg]` 10건은 본 Phase 범위 밖 (Repository import 자체가 strict 검증 대상이라 표시되지만, Phase 1에서 추가한 `ProposalRepository`는 깨끗함).

### baseline_kpis 재측정

`docs/harness/phase1_baseline.json` 저장. markdown 파서 기반이라 Phase 0과 동일한 분포(제안서 37건, implemented 36, unknown 1, success_rate 100%). **다음 cadence부터** Phase 2의 trajectory 적재가 이 KPI를 DB 기반으로 교체한다.

---

## 6. 운영 가이드 (신규 사용자 인터페이스)

### 6.1 자동 사이클 일시 중단 / 재개

```bash
# Telegram 봇이 떠 있을 때
/pause_implement         # 중단 (pause lock 설치)
/pause_implement resume  # 재개 (pause lock 제거)

# 또는 직접 파일 조작
touch ~/.kis-autotrader/harness-paused     # 중단
rm ~/.kis-autotrader/harness-paused         # 재개
```

### 6.2 즉시 1회 사이클 발동

```bash
# Telegram
/run_implement          # 가드 통과 → 즉시 launchctl start com.kis.autoimplement
/run_implement --dry    # 가드만 통과 (실제 사이클 발동 안 함)
/run_implement --force  # KIS_ENV=real + 장중에도 발동 (주의)

# CLI
scripts/trigger_implement.sh
scripts/trigger_implement.sh --dry
scripts/trigger_implement.sh --force
```

### 6.3 현재 상태 조회

```bash
/status_implement       # paused 여부 + 현재 사이클 (claude-progress.json 기반)
```

### 6.4 가드 동작

| 가드 | 차단 조건 |
|------|----------|
| pause lock | `~/.kis-autotrader/harness-paused` 파일 존재 |
| cycle in-flight | `~/.kis-autotrader/harness-cycle-in-flight` 파일 존재 (이중 발동 방지) |
| 최소 인터벌 | 마지막 사이클 완료로부터 `HARNESS_MIN_CYCLE_INTERVAL_SECONDS` (default 300s) 이내 재발동 차단 |
| 장중 가드 | `KIS_ENV=real` + 평일 09:00~15:30 KST + `--force` 없으면 차단 |

---

## 7. 결론

Phase 1은 RFC 13 task 모두 봉인. **D3/D4/D5/D7/D10 5개 진단을 직접 해결**:

- D3 (안전 게이트 자연어) → hook 4종 deterministic 코드화
- D4 (제안서 상태 markdown 의존) → `proposals` DB + Repository
- D5 (실패 복구 자동화 부재) → pause lock + cycle lock + claude-progress.json 기반 복구 토대
- D7 (골든 회귀 셋 부재 사전 차단) → DTZ ruff 룰셋(Phase 0)이 이미 차단, hook의 PostToolUse가 추가 신호
- D10 (트리거 cron 단일) → CLI + Telegram 3개 + pause/resume

**Phase 2 진입 준비**: Verifier 서브에이전트 분리, Initializer를 사이클 entry point에 wiring, 골든 회귀 셋, trajectory 적재. 본 Phase가 데이터 계층과 안전 게이트의 토대를 만들었으니 Phase 2는 그 위에 실행 엔진의 책임 분리를 쌓는다.
