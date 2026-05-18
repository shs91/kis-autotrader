# 하네스 Phase 3 완료 리포트

> **작성일**: 2026-05-15 (KST)
> **워크트리**: `kis-autotrader-harness` / 브랜치 `feat/harness-phase1`
> **RFC**: [`docs/plans/2026-05-15_harness-phase3-rfc.md`](../plans/2026-05-15_harness-phase3-rfc.md)
> **Phase 2 완료**: [`phase2_completion.md`](./phase2_completion.md)

---

## 1. 11 Task 봉인 결과

| Task | 산출물 | 커밋 |
|------|--------|------|
| T1 | `Initializer` 모듈 — alembic/git/venv/disk 점검 + cycle_id + progress.json | `a65ade0` |
| T2 | Pipeline CLI read 3종 (list_ready/find_proposal/last_safe_tag) | `6b901a6` |
| T3 | Pipeline CLI mark 4종 (in_flight/implemented/failed/skipped) + SQLite TIMESTAMPTZ 보정 | `52ae4c5` |
| T4 | Pipeline CLI append_progress | `8083048` |
| T5 | 제안서 독립 그룹 (Union-Find) | `92bd98b` |
| T6 | `.claude/agents/` 5종 (proposal-validator/implementer/verifier/evaluator/rollback-handler) | `d04bce3` |
| T7 | `.claude/skills/` 4종 (proposal-validation/kis-api-rate-limit-pattern/strategy-add-pattern/alembic-migration-flow) | `59c768e` |
| T8 | `auto_implement_prompt_v2.txt` — subagent 오케스트레이션 prompt | `532c2dc` |
| T9 | Cycle Orchestrator (`src/harness/cycle/orchestrator.py`) | `f908a71` |
| T10 | `run_auto_implement.sh` — Initializer + prompt_v2 전환 | `582ea9f` |
| T11 | 본 리포트 + lint cleanup | (본 커밋) |

> **신규 테스트**: 약 22건 추가. Phase 1·2 통합 시 누적 **120 passed** (`pytest tests/test_harness/ tests/eval/ -q` → `120 passed in 3.77s`).

---

## 2. 5계층 ADK 충족 매핑 (축 D)

| 계층 | Phase 3 산출물 |
|------|----------------|
| **CLAUDE.md** (always-on) | 기존 유지 (이전 Phase에서 핵심만 남김) |
| **Skills** (on-demand) | `.claude/skills/` 4종 — proposal-validation/rate-limit/strategy-add/alembic-flow |
| **MCP** (외부 도구) | **Pipeline CLI 8종으로 대체** (외부 MCP SDK 의존 회피). `list_ready/find_proposal/last_safe_tag/mark_in_flight/mark_implemented/mark_failed/mark_skipped/append_progress` |
| **Subagents** (격리 컨텍스트) | `.claude/agents/` 5종 — proposal-validator/implementer/verifier/evaluator/rollback-handler |
| **Hooks** (deterministic gate) | Phase 1에서 이미 완성 (`.claude/settings.json` + `scripts/claude-hooks/run_hook.py`) |

---

## 3. 진단 해결 매핑

| 진단 (계획서 §3) | Phase 3 해결 |
|------------------|--------------|
| D1 컨텍스트 인계 부재 | T1 Initializer가 매 사이클 `claude-progress.json`을 생성, 모든 subagent가 동일 파일을 봄 |
| D8 단일 거대 프롬프트 | T8 prompt_v2 + T6 agents 분해 — 90줄 prompt → 20~30줄 agent 6개로 분산 |
| Phase 1·2 이관: progress wiring | T1 Initializer 호출 + T9 orchestrator가 cycle 종료 시 progress.json 통계로 outcome 결정 |
| Phase 2 `apply_verification_result` 사이클 wiring | T9 orchestrator의 `run_cycle()`이 결과를 받아 progress에 반영. 실제 mark_* 호출은 verifier agent가 Pipeline CLI로 수행 |
| 축 D 병렬화 | T5 독립 그룹 계산 + T8 prompt_v2가 그룹 단위 병렬 dispatch 명시 |

---

## 4. 검증 요약 (T11 실행 결과)

### pytest 누적
- `tests/test_harness/` + `tests/eval/` → **120 passed in 3.77s**
- 신규 모듈 회귀: 0
- 사전 존재 실패는 본 Phase 범위 밖 (시간 의존 flake + test_models.py JSONB workaround 누락)

### ruff
- Phase 3 신규 모듈: **All checks passed** (T11에서 import 정렬 + N806 lowercase 1건 정리 후)

### mypy --strict
- Phase 3 신규 모듈: **0 errors**
- 의존 모듈 `src/db/repository.py`에 사전 존재 `dict[type-arg]` 10건은 본 Phase 범위 밖

### Initializer smoke test
```bash
PYTHONPATH=. .venv/bin/python -c "from src.harness.initializer import Initializer; ..."
# → cycle_id=auto-20260515-184224 / all_pass=False
```
- 워크트리 자체에 `.venv` 심볼릭 링크 등 untracked 파일이 있어 `git_clean` 체크가 FAIL — 정상 동작 (실제 메인 repo에서는 `.venv`가 gitignored 등록되어 있어 PASS 가능)
- 그 외 alembic head / venv 존재 / disk free 모두 PASS

---

## 5. 운영 영향 / 머지 시 주의

본 Phase 3도 워크트리에 한정. 핵심 영향:

### 5.1 시스템 영향 (현재 = 워크트리 한정)

- `.claude/agents/` 5종 + `.claude/skills/` 4종: 워크트리 `.claude/`에만 존재. `.gitignore`로 차단되어 있어 `git add -f`로 강제 스테이징했지만, 메인 repo의 `.gitignore`도 동일하므로 머지 시 동일 처리 필요
- `scripts/auto_implement_prompt_v2.txt`: 새 prompt. 메인 repo의 cron이 V2를 호출하려면 머지 + `scripts/run_auto_implement.sh` 갱신 함께
- `scripts/run_auto_implement.sh`: 단일 `claude -p` → `run_cycle()` Python 호출로 변경
- `src/harness/initializer.py` + `src/harness/cycle/orchestrator.py`: 새 모듈. 메인 repo에 없음
- `src/harness/dependency.py`: 새 모듈
- 8종 Pipeline CLI: 새 스크립트
- `src/db/session.py`: SQLite TIMESTAMPTZ 보정용 load 이벤트 핸들러 추가. **PostgreSQL은 무영향** (이미 aware로 반환). 운영 autotrader에는 변화 없음

### 5.2 머지 시 결정 사항

1. `.claude/agents/` + `.claude/skills/`을 메인 repo에 머지하면, **메인의 모든 Claude Code 세션에서도 5종 agent + 4종 skill이 사용 가능**해진다. 운영자가 의도하면 머지, 그렇지 않으면 워크트리 한정 유지
2. `auto_implement_prompt_v2.txt` + `run_auto_implement.sh` 변경분 머지 시점: 머지 → 다음 평일 17:00 cron 도착 전 `launchctl unload com.kis.autoimplement` → reload → 첫 사이클 동작 관측 권장
3. Pipeline CLI 8종: 메인 repo 머지 후 `chmod +x` 필수 (gitignore로 mode 무시될 수 있음)
4. `src/db/session.py` load 핸들러: 머지해도 PostgreSQL 운영 영향 없음. SQLite 테스트 경로만 영향

### 5.3 운영 상태 (현재)

서비스 운영 정상 (Phase 2 완료 리포트 시점 재로드 완료):
- `com.kis.autotrader` PID 81079 — 운영 중
- `com.kis.watchdog` / `com.kis.autoimplement` — 스케줄 대기
- `com.kis.dashboard` PID 785 — 운영 중

---

## 6. Phase 4 진입 준비

Phase 3가 만든 토대 위에서 Phase 4가 다룰 항목 (harness plan §5 Phase 4, 축 C):

1. **trajectory 테이블 신설** — 사이클 단계별 입력/결과/시간/토큰 사용량 적재 (`progress.json.history`를 DB로 영속화)
2. **component metadata** — `implementation_logs.changed_files`에 `component` 분류 추가 (code/strategy/api/db, prompt, skill, subagent, hook)
3. **decision prediction** — 제안서의 "기대 효과"를 정량 prediction으로 기록, 다음 주간 리포트에서 실측 대조
4. **대시보드 신규 페이지** — `dashboard/pages/pipeline.py`. 사이클 success rate, MTTR, top failure reasons, component edit heatmap, prediction calibration
5. **Telegram 결산 강화** — 평문 → 3섹션 카드 (오늘 적용 + 회귀 위험 + 예측 미달)

Phase 3는 **5계층 ADK의 실행 토폴로지**를 정리했으므로 Phase 4는 **trajectory를 데이터 자산화**해 하네스가 자기 자신을 측정·개선할 수 있는 상태로 만든다.

---

## 7. 결론

Phase 3 RFC 11 task 모두 봉인. 5계층 ADK의 4개 계층(CLAUDE.md/Skills/Subagents/Hooks + MCP 대체로서 Pipeline CLI)이 모두 실체화됨. 단일 `claude -p` 거대 프롬프트는 Initializer + 5 agent + Pipeline CLI 8개로 분해. 다음 사이클부터:

- **각 사이클이 cycle_id로 식별되고 claude-progress.json에 진척이 기록됨**
- **5 agent가 격리된 컨텍스트에서 자기 책임 영역만 처리**
- **독립 제안서는 병렬 처리, 의존 있는 것만 직렬**
- **Pipeline CLI로 proposals 상태가 결정적으로 전이**

Phase 4는 본 인프라가 만든 trajectory를 데이터 자산으로 영속화해 3축 Observability를 완성한다.
