# 하네스 Phase 2 완료 리포트

> **작성일**: 2026-05-15 (KST)
> **워크트리**: `kis-autotrader-harness` / 브랜치 `feat/harness-phase1`
> **RFC**: [`docs/plans/2026-05-15_harness-phase2-rfc.md`](../plans/2026-05-15_harness-phase2-rfc.md)
> **Phase 1 완료**: [`phase1_completion.md`](./phase1_completion.md)

---

## 1. 13 Task 봉인 결과

| Task | 산출물 | 커밋 |
|------|--------|------|
| T1 | `verifier/diff.py` — `parse_numstat` + `DiffSummary.to_jsonb` + TDD 5 | `f67e88d` |
| T2 | `verifier/parsers.py` ruff 파서 + TDD 4 | `6475999` |
| T3 | `verifier/parsers.py` pytest junit XML 파서 + TDD 4 (xml.etree) | `1a4cc28` |
| T4 | `verifier/parsers.py` mypy text 파서 + TDD 4 (regex) | `81bcebc` |
| T5 | `verifier/contract.py` Default-FAIL 평가기 + TDD 7 | `d3c8549` |
| T6 | `verifier/runner.py` 통합 실행기 + TDD 3 (subprocess mock) | `317c754` |
| T7 | `scripts/harness/run_verifier.py` CLI + `--self-test` + TDD 2 | `d6376a6` |
| T8 | `golden/loader.py` manifest 스키마 + TDD 4 (StrEnum) | `3607aa1` |
| T9 | 골든 케이스 10건(G01~G10) 등록 + 3건 패턴 조정 | `6853ff4` |
| T10 | `golden/runner.py` invariant runner + 통합 11건 회귀 | `158e5ce` |
| T11 | `verifier/cycle.py` contract → proposals 상태 전이 + TDD 3 | `e3794cc` |
| T12 | `run_auto_implement.sh` 골든+Verifier 통과만 서비스 재시작 | `c7aabb0` |
| T13 | 본 리포트 | (본 커밋) |

> **신규 테스트**: Phase 2에서 **52건 추가**. Phase 1(58) + Phase 2(52) = **110 신규 테스트 모두 통과** (`pytest tests/test_harness/ tests/eval/ tests/test_db/test_proposals_repository.py tests/test_notify/test_harness_commands.py -q` → `110 passed`).

---

## 2. Phase 1 §3 이관 항목 충족

`phase1_completion.md` §3에서 Phase 2로 이관된 두 항목:

| 이관 항목 | Phase 2 충족 위치 |
|----------|------------------|
| `changed_files` JSONB 자동 채움 | T1 `parse_numstat → DiffSummary.to_jsonb()`. Verifier가 git diff을 추출해 `implementation_logs.verification.artifacts.diff`에 저장. 향후 record_implementation.py 호출 시 자동 채움 |
| Verifier 서브에이전트 분리 (fresh-context, Write/Edit 금지) | T6/T7. `VerifierRunner`는 stdlib subprocess만 사용해 pytest/mypy/ruff/git diff을 실행. **Claude Code 컨텍스트와 완전히 격리** — 단일 외부 명령 호출만 함 |
| Default-FAIL contract | T5. pytest/mypy/ruff/diff 4종 증거 중 하나라도 부재 또는 자체 실패면 contract FAIL |
| 골든 회귀 셋 (10건 + 사이클 시작 직전 runner) | T8/T9/T10. `tests/eval/golden_proposals/G01~G10` + `tests/eval/test_golden_runner.py`. `run_auto_implement.sh`가 매 사이클 시작 시 호출 |

Phase 1 §3의 **"실제 사이클 시작 시 `claude-progress.json` 생성 wiring"**은 Phase 3 Initializer로 추가 이관.

---

## 3. 검증 요약 (T13 실행 결과)

### pytest 신규 카운트
- `tests/test_harness/` + `tests/eval/` + 신규 wiring 테스트 → **110 passed in 0.71s**
- 사전 존재 실패(Phase 1 §5에서 명시) 5건은 본 Phase 범위 밖 — 시간 의존 flake 4건 + `test_get_optimal_risk_params` 1건 — 메인 repo와 동일

### ruff (Phase 2 신규)
- `ruff check src/harness/verifier/ src/harness/golden/ scripts/harness/run_verifier.py tests/test_harness/ tests/eval/` → **All checks passed!**

### mypy --strict (Phase 2 신규)
- `mypy --strict src/harness/verifier/ src/harness/golden/ scripts/harness/run_verifier.py` → **0 errors on new code**
- 의존 모듈 `src/db/repository.py`에 사전 존재 `dict[type-arg]` 10건은 Phase 2 범위 밖 (P1-T3 봉인된 모듈)

### Verifier CLI end-to-end (`--self-test`)
```bash
PYTHONPATH=. .venv/bin/python -m scripts.harness.run_verifier \
  --self-test --out /tmp/verifier_selftest.json
```
출력: `passed: true, reasons: [], artifacts: {pytest, mypy, ruff, diff}`, exit 0 ✓

### 골든 회귀 11건 실측 (Phase 2 T10)
- 10건 manifest + 1건 카운트 검증 → **11 passed**
- 패턴 조정 3건: G01 (engine.py datetime.now timestamp 컨텍스트 면제), G08 (notify_error 실제 시그니처 `context, error`), G10 (alembic 마이그레이션 줄바꿈 대응 DOTALL)

---

## 4. 진단 해결 매핑

| 진단 (계획서 §3) | Phase 2 해결 |
|------------------|-------------|
| D2 자기보고 grep 기반 검증 | T6 Runner가 4종 증거 수집 → T5 contract가 Default-FAIL로 채점 |
| D6 관측성: `changed_files` JSONB 0건 | T1 git diff 파서가 표준 JSONB 스키마 채움 |
| D6 관측성: 실패 traces 부재 | T11 `apply_verification_result`가 실패 시 `mark_failed(reason=...)`로 DB 적재 |
| D7 골든 회귀 셋 부재 | T8/T9/T10. 10건 + 4 invariant type + 사이클 직전 자동 회귀 |
| Phase 1 §3 이관: Verifier 서브에이전트 분리 | T6/T7 (코드 격리) — `.claude/agents/verifier.md` 선언 자체는 Phase 3 ADK 1:1 매핑 시점 |

---

## 5. 운영 영향 / 머지 시 주의

본 Phase 2도 워크트리에 한정. 핵심 영향:

### 5.1 시스템 영향 (현재 = 워크트리 한정)

- `tests/eval/golden_proposals/`: 메인 repo에는 없음. 머지 후 신규 디렉토리 생성됨
- `scripts/harness/run_verifier.py`: 메인 repo에는 없음. 머지 시 추가
- `scripts/run_auto_implement.sh`: 메인 repo 버전은 골든/Verifier wiring 없음. 머지 시 변경
- `.env` / DB: 변화 없음. proposals 테이블은 Phase 1에서 이미 적용됨

### 5.2 머지 시 결정 사항

1. **`run_auto_implement.sh`의 골든+Verifier wiring**: 머지하면 매 사이클 시작 시 `tests/eval/` 회귀 실행 + Verifier가 contract 채점. 골든 1건이라도 실패하면 서비스 재시작 차단. 일종의 **자기보호 모드**. 권장: 머지
2. **`verifier_*.json` 아티팩트 로그 폴더**: `$LOG_DIR/verifier_YYYY-MM-DD_HHMMSS.json`. Phase 3에서 trajectory 테이블로 이전 시까지 디스크에만 누적. 7일 롤링 정리 cron 권장 (별도 제안서)
3. **`apply_verification_result` 사용처 wiring**: 본 Phase는 함수 정의만. 실제 호출(=cycle 마지막에 호출되어 IN_FLIGHT → IMPLEMENTED/FAILED 자동 전이)은 Phase 3 Initializer 토폴로지가 cycle 흐름 책임지면서 wiring. 현 시점에서는 `run_auto_implement.sh`가 grep("implemented") 휴리스틱 + Verifier exit code로 보강된 결정만 함

### 5.3 운영 재개 (현재 unload 상태)

```bash
launchctl load ~/Library/LaunchAgents/com.kis.autotrader.plist
launchctl load ~/Library/LaunchAgents/com.kis.watchdog.plist
launchctl load ~/Library/LaunchAgents/com.kis.autoimplement.plist
launchctl list | grep kis
```

---

## 6. Phase 3 진입 준비

Phase 2가 만든 토대 위에서 Phase 3가 쌓을 항목 (harness plan §5 Phase 3, 축 D):

1. **Initializer 서브에이전트** — 사이클 entry point 전환 (`claude -p` 단일 호출 → Initializer가 환경 점검 + `claude-progress.json` 생성 + 다음 단계 위임)
2. **`.claude/agents/`에 5종 선언**: initializer / proposal-validator / implementer / verifier / rollback-handler
3. **Pipeline MCP 서버**: `list_ready_proposals`, `mark_in_flight`, `mark_implemented`, `mark_failed`, `append_progress`, `last_safe_tag` 6~8개 도구
4. **병렬화**: 독립 제안서(파일 경로 비교집합)를 worker pool로 처리
5. **`apply_verification_result` 실제 wiring**: Initializer가 사이클 전이 책임지면서 호출

Phase 2는 **검증/회귀 인프라**를 완성했으므로 Phase 3는 **실행 토폴로지의 책임 분리**에 집중한다.

---

## 7. 결론

Phase 2 RFC 13 task 모두 봉인. 신규 테스트 52건 + 골든 10건이 모두 첫 실행에서 통과. 진단 D2/D6/D7 + Phase 1 §3 이관 항목 4종 충족. 다음 사이클부터:

- **자기보고 grep 휴리스틱이 deterministic contract로 대체됨**
- **실패 traces가 `proposals.failure_reason` + `verifier_*.json`에 자동 적재됨**
- **동일 카테고리 회귀(DTZ, notify_error 시그니처, 마이그레이션 head 등)가 사이클 시작 시 사전 차단됨**

Phase 3는 본 인프라를 5계층 ADK(서브에이전트·MCP·병렬화)로 정리한다.
