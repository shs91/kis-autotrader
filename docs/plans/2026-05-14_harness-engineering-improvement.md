# 하네스 엔지니어링 기반 자동 구현 파이프라인 개선 계획

> **상태**: draft (방향성 문서)
> **작성일**: 2026-05-14
> **작성자**: Cowork
> **상세도**: 고수준 방향성 — 세부 RFC/제안서는 본 문서의 Phase별 액션에서 분리 작성

---

## 1. 배경과 목적

이 프로젝트는 이미 Cowork(분석/기획) ↔ Claude Code(구현)가 `docs/proposals` ↔ `docs/CHANGELOG.md` ↔ `implementation_logs` 테이블을 브릿지로 사용해 **사람 승인 없이 동작하는 자동 구현 파이프라인**을 운영하고 있다. 평일 17:00 cron이 `scripts/run_auto_implement.sh`를 호출하고, watchdog/health 서버가 런타임을 감시하며, SemVer 자동 bump와 git tag로 롤백 지점을 봉인하는 구조는 일반적인 “LLM CLI 호출 스크립트” 단계를 분명히 넘었다.

**현재 분석/리포트 cadence의 운영 현실은 다음과 같다.** Cowork는 지금 **주간·월간 분석만 실효적으로 수행**하고 있다. 일일 리포트는 BRIDGE_SPEC에 규격이 정의되어 있고 launchd plist(`com.kis.dailyanalysis.plist`)도 존재하지만 Cowork 측 분석 사이클이 일관되게 돌고 있지 않으며, **분기 리포트는 규격·트리거·템플릿 모두 미정의 상태**이다. 즉 의사결정 입력(리포트)이 지금은 “주 1회 + 월 1회”라는 두 박자에 머무르고 있어, 일중 변동·계절성·중장기 전략 평가의 시간 해상도가 비대칭적이다.

**본 계획의 궁극 목표는 분명하다.** 일간·주간·월간·분기 **네 cadence 모두를 동일한 하네스 토폴로지**(Initializer → Data Auditor → Analyst → Critic → Proposal Synthesizer)로 회전시켜, 각 cadence가 자신의 시간 해상도에 맞는 ready 제안서를 안전 게이트를 사전 통과시킨 상태로 생성하고, 그 제안서들이 동일한 자동 구현 사이클을 통해 봉인된다. 일간은 “장 종료 직후 핫픽스성 미세 조정”, 주간은 “파라미터 튜닝·전략 보정”, 월간은 “전략 유효성 재평가”, 분기는 “포트폴리오·리스크 한도·아키텍처 방향성”을 담당하는 식으로 cadence별 역할을 분리한다.

그러나 2026년 들어 업계가 **harness engineering**(혹은 **agentic harness engineering**)이라는 이름으로 정리하고 있는 새로운 정합성·관측성·자기진화 패턴들과 비교해 보면, 현재 시스템은 다음 영역에서 구조적 한계를 노출하고 있다.

1. **컨텍스트 인계의 부재** — 매 사이클마다 LLM이 zero memory로 시작하고, 진척 상태를 `.md` 파일 더미에서 재구성한다.
2. **검증의 자기보고 의존** — pytest/mypy/ruff 결과 grep만 통과하면 `implemented`로 봉인된다. 독립적인 fresh-context 평가가 없다.
3. **안전 게이트가 prompt 텍스트로만 표현됨** — `.env` 금지·파라미터 범위·5파일 제한 등 규칙이 BRIDGE_SPEC 문서에 자연어로 적혀 있어 실행 시점 강제가 약하다.
4. **관측성·평가 인프라 부재** — 어떤 제안서가 어떤 컴포넌트(프롬프트/도구/스킬/서브에이전트)에 영향을 주었는지, 사이클별 성공률·롤백률·재발 패턴이 코드 외부 어디에도 집계되지 않는다.
5. **단일 에이전트 단일 컨텍스트** — 한 번의 `claude -p` 호출에 “안전 검증, 구현, 검증, 롤백, 기록, 재시작”을 모두 떠넘긴다. 서브에이전트·스킬·훅 같은 Claude Code 네이티브 분리 메커니즘이 사용되지 않는다.

본 문서의 목표는 위 한계를 4개의 축으로 정리하고, **하네스 엔지니어링** 관점에서의 개선 방향과 단계적 로드맵을 합의 가능한 수준까지 제시하는 것이다. 세부 구현은 본 문서가 승인된 이후, Phase별 RFC/제안서로 분리 작성한다.

---

## 2. 하네스 엔지니어링이란 (용어 정렬)

업계 합의는 비교적 명료하다. **Agent = Model + Harness**라는 식으로, 모델을 제외한 모든 런타임 인프라(메모리, 도구 디스패치, 컨텍스트 관리, 안전 게이트, 세션 상태, 관측, 평가)를 **하네스**라 부른다. 하네스가 “모델의 OS”라는 표현이 자주 쓰인다(MongoDB, Adnan Masood 등).

Anthropic은 2025-11 발행한 *Effective harnesses for long-running agents*에서 장시간/다세션 에이전트에 필수적인 세 가지 구조를 정리했다.

- **Initializer–Verifier–Explorer 분리**: 첫 세션은 환경 세팅 전용 프롬프트로 `init.sh`/`claude-progress.txt`/초기 git 커밋을 만든다. 이후 세션은 모두 “지금까지의 진척을 읽고 → 작은 단위 진척 → 구조화된 업데이트 남김” 루프만 수행한다.
- **Fresh-context evaluator**: Write/Edit 도구를 박탈한 별도 서브에이전트가 빌드를 본 적 없는 컨텍스트에서 결과를 채점한다. 자기평가의 편향 차단이 핵심.
- **Default-FAIL contract**: 모든 검수 기준은 false에서 시작하고, 에이전트는 명시적 증거를 제시한 후에만 통과 마킹할 수 있다.

같은 시점에 발표된 *Agentic Harness Engineering*(arXiv 2604.25850)은 한 발 더 나가 “하네스 자체가 관측·진화 대상”이라는 패러다임을 제안한다. 세 가지 관측성 축으로 ① **component observability**(편집 가능한 하네스 컴포넌트 — 시스템 프롬프트, 도구 설명/구현, 미들웨어, 스킬, 서브에이전트, 장기 메모리 — 각각을 파일 단위로 표현), ② **experience observability**(실행 trajectory를 layered evidence corpus로 정제), ③ **decision observability**(매 편집에 self-declared prediction을 붙이고 다음 라운드 결과로 검증)을 둔다.

Claude Code 네이티브 ADK는 이를 5계층으로 표현한다. **CLAUDE.md**(always-on context), **Skills**(on-demand workflow), **MCP**(외부 도구/데이터), **Subagents**(격리된 컨텍스트), **Hooks**(라이프사이클 결정점에서의 deterministic gate). 본 계획은 이 5계층을 1:1로 활용한다.

---

## 3. 현황 진단

| # | 현상 | 영향 | 근거 |
|---|------|------|------|
| D1 | LLM 세션이 매 사이클마다 zero memory로 시작, 진척 상태는 `.md` 더미에서 재구성 | 컨텍스트 재로딩 비용/오해, 누락 위험 | `run_auto_implement.sh`가 매번 BRIDGE_SPEC + 모든 ready 제안서를 처음부터 로드 |
| D2 | 검증이 자기보고 grep 기반 (`pytest`, `mypy`, `ruff` 출력 “OK” 매칭) | 미커버 영역의 회귀가 implemented로 봉인됨 | 2026-05-12~13 naive datetime 버그가 동일 패턴으로 2일 연속 재발 |
| D3 | 안전 게이트가 BRIDGE_SPEC 자연어 규칙 + 프롬프트 의존 | 규칙 위반이 사후 발견됨, 신뢰가 모델 준수도에 종속 | `.env`/credentials 금지, 5파일 제한, 파라미터 범위 등 모두 텍스트 |
| D4 | 제안서 상태 머신이 markdown 파일의 `상태: ready` 라인 편집에 의존 | 동시성/일관성 보장 없음, 외부 도구가 상태 질의 불가 | 37개 제안서를 cron 단일 실행으로만 직렬 처리 |
| D5 | 실패 복구가 “git restore + failed 마킹”에 머무름 | 부분 적용/스테이지 잔존 위험, 환경 점검 자동화 없음 | `auto_heal.sh` 하루 1회 제한, watchdog와 별도 |
| D6 | 관측성이 logfile + Telegram 평문에 머무름 | 사이클별 KPI(성공률, 재시도율, MTTR)·구조적 분석 불가 | `implementation_logs`는 성공 사례만 적재, 실패 traces 부재 |
| D7 | 제안서 카테고리만 있고 골든 회귀 셋이 없음 | 동일 종류 버그(타임존, rate limit)의 재발을 사전 차단할 evaluator 부재 | ruff DTZ 규칙 미활성, datetime.now() 정적 차단 없음 |
| D8 | 단일 `claude -p`가 안전/구현/검증/롤백/기록을 모두 수행 | 컨텍스트 폭발, 책임 경계 모호, 병렬화 불가 | `auto_implement_prompt.txt` 90줄 단일 프롬프트 |
| D9 | 일일/주간 리포트도 동일 단일 프롬프트 구조 — 수치·결론 정합성 자기보고, 제안서 split 수동 | 리포트가 “LLM이 데이터에서 본 인상”에 가까워지고, 다음 사이클의 결정 근거로서의 신뢰도가 낮음 | 단일 `claude -p`로 `query_analytics.py` JSON → 마크다운 변환 |
| D10 | 트리거가 cron 단일 채널 — 운영 중 즉시 발동, 이벤트 발동, 안전 일시 정지 등의 운영 도구가 없음 | 핫픽스 직후 사이클을 “지금 한 번만” 돌리고 싶을 때 수동 우회/터미널 SSH 필요 | `launchctl start` 수동 호출 외 표준 경로 없음 |
| D11 | 리포트 cadence가 “주간 + 월간” 두 박자에 멈춰 있음 | 일중 변동·계절성·중장기 전략 평가의 시간 해상도 비대칭. 일간 결정은 사람 직관에 의존, 분기 단위 구조 점검은 아예 부재 | 일일 plist는 존재하나 Cowork 분석 사이클이 비안정, 분기 리포트는 규격·템플릿·트리거 전무 |

> 위 D1~D11은 다음 절의 5개 개선 축이 각각 어떤 진단을 해결하는지 매핑된다.

---

## 4. 개선 축

### 축 A. 아키텍처 재설계 — Initializer–Worker–Verifier 분리 + 5계층 ADK 채택

**해결 진단**: D1, D3, D8

**왜**: 단일 거대 프롬프트는 모델이 “규칙 기억 → 구현 → 자기검증”을 한 번에 처리해야 하므로 컨텍스트가 가장 비쌀 때(구현 직후) 가장 약하다. 책임 분리는 LLM뿐 아니라 사람 엔지니어도 동일한 이유로 한다.

**무엇을 한다**

- 자동 구현 사이클을 다음 **에이전트 토폴로지**로 재구성한다.
  - **Initializer** (1회/사이클 시작): KIS_ENV·DB·alembic head·venv·디스크·git 클린 여부를 점검하고 `claude-progress.json`을 만든다. 이후 모든 워커는 이 파일에서 시작 상태를 읽는다.
  - **Proposal Validator (subagent)**: 각 `ready` 제안서를 JSON Schema로 검증(파일별 변경 셀, 카테고리, 파라미터 범위 합계 등). 위반은 즉시 `skipped`로 DB 기록.
  - **Implementer (subagent, per proposal)**: Write/Edit/Bash만 보유. 단일 제안서 1건만 컨텍스트에 둔다.
  - **Verifier (fresh-context subagent, Write/Edit 금지)**: 변경된 파일 diff + 테스트/타입/린트 출력만 받아 Default-FAIL contract로 채점. 통과 증거(JSON)를 반환.
  - **Recorder/Tagger**: `record_implementation.py` 호출 + git tag + Telegram 결산.
  - **Rollback Handler**: Verifier가 FAIL이면 git restore + DB `failed` + 실패 사유 구조화.
- **Claude Code 5계층 ADK 1:1 매핑**
  - **CLAUDE.md**는 “always-on” 최소핵심(코딩 컨벤션, 환경변수 prefix, 모듈 경계)만 남기고, 자동 파이프라인 세부 규약은 Skills로 이동.
  - **Skills** (`.claude/skills/*/SKILL.md`)에 `proposal-validation`, `kis-api-rate-limit-pattern`, `alembic-migration-flow`, `strategy-add-pattern` 등을 트리거 기반으로 분리. CLAUDE.md 컨텍스트가 가벼워지고 필요 시에만 로드된다.
  - **MCP**: 이미 보유한 `mcp__kis-postgres__query` 외에 **proposal/implementation MCP 서버**를 신설해 `list_ready_proposals`, `update_status`, `record_implementation`을 단일 API로 제공. md 파일 직접 편집 의존을 제거.
  - **Subagents**: 위 5종 토폴로지를 `.claude/agents/` 마크다운으로 선언, 권한 매트릭스 명시.
  - **Hooks** (`.claude/settings.json`): 안전 게이트를 **deterministic**하게 강제 (다음 축에서 상세).
- **`claude-progress.json` 스키마** (Anthropic 패턴 차용)
  - `cycle_id`, `started_at`, `initializer_checks`(통과/실패 항목), `pending`, `in_flight`, `completed`, `failed` 제안서 목록과 상태 전이 history.
  - 다음 사이클은 이 파일과 git tag만 보고 “현재 안전한 시점”을 이해할 수 있어야 한다.

**기대 효과**: 단일 프롬프트 90줄 → 에이전트별 평균 20~30줄. 컨텍스트 폭발 방지. 병렬 구현(서브에이전트 worker pool)으로 17:00~완료 시간 축소.

#### 사이클 트리거 메커니즘 (D10 해소)

자동 사이클이 “언제 시작되는가”에 대한 표준 채널을 명시한다. 동일한 Initializer 진입점을 공유하되 발동 경로를 다음 세 가지로 둔다.

- **스케줄 트리거** (기본, 운영 표준)
  - `com.kis.autoimplement.plist`(평일 17:00) 그대로 유지. 가장 보수적이고 예측 가능한 채널.
  - 일일/주간 리포트 cron(축 E 참조)이 ready 제안서를 생성하면, 그 다음 사이클(=다음 평일 17:00)에서 일괄 처리되는 흐름이 기본.
- **이벤트 트리거** (Phase 3 이후 옵션)
  - `proposals` 테이블에 `state=ready`가 INSERT 되면 “Pipeline MCP” 서버가 발동 이벤트를 큐잉. 운영 시간 외에는 큐에 머무르고, 다음 trading-day 17:00에 합산 처리.
  - critical 우선순위 제안서에 한해 “장 종료 직후 즉시 1회 사이클” 옵션을 둘 수 있지만, 기본은 OFF로 시작.
- **수동 트리거** (D10의 직접 해소)
  - **Telegram 봇 명령**
    - `/run_implement` — 즉시 1회 사이클 시작 (현재 ready인 제안서들 대상).
    - `/run_implement --dry` — 안전 게이트와 Verifier만 돌리고 구현은 하지 않는 dry-run.
    - `/pause_implement [hours]` / `/resume_implement` — 스케줄·이벤트 트리거 일시 정지 (운영 점검 중 또는 장중 사고 시).
    - `/status_implement` — 현재 사이클 단계와 in-flight 제안서.
  - **CLI 스크립트** `scripts/trigger_implement.sh [--dry] [--proposal <path>]`
    - 단일 제안서만 시도하는 옵션 포함. SSH로 운영 머신에 들어가지 않아도 launchd label 호출만 표준화.
  - **대시보드 버튼** (`dashboard/pages/pipeline.py`)
    - 동일 동작을 GUI로. 대시보드 인증 범위 내에서만 동작.
  - **안전 가드 (수동·이벤트 공통)**
    - 동시 실행 방지: `claude-progress.json`의 `cycle_id`가 `in_flight`면 즉시 reject.
    - 최소 인터벌: 마지막 완료 사이클로부터 5분 이내 재발동 차단(연속 클릭 사고 방지).
    - `KIS_ENV=real`이고 장중(09:00~15:30) 시간대일 때는 수동·이벤트 트리거를 기본 차단, `--force` 플래그 + Telegram 2단계 확인 필요.
    - 모든 수동 트리거는 “누가, 어떤 채널로” 발동했는지 `trajectory` 테이블에 기록(축 C의 Experience Observability).

---

### 축 B. 자동 구현 파이프라인 안정성 — 안전 게이트의 “텍스트 → 코드” 이전, 복구 자동화

**해결 진단**: D3, D5, D7

**왜**: 안전 규칙이 자연어로만 존재하면 모델이 “준수하려고 노력”하는 데 그친다. 하네스 엔지니어링의 핵심 정리는 **deterministic gate**(훅·검증 스크립트·정적 분석)와 **advisory rule**(프롬프트·CLAUDE.md)을 분리하는 것이다.

**무엇을 한다**

- **Hooks 기반 결정적 안전 게이트** (`.claude/settings.json`)
  - `PreToolUse(Edit|Write)`: 변경 대상 경로가 금지 목록(`.env`, `credentials.json`, `token.json`, `alembic/versions/*`, `pyproject.toml`의 dependencies 라인)에 닿으면 즉시 차단.
  - `PreToolUse(Bash)`: `git push --force`, `rm -rf`, `psql ... DROP` 등 위험 패턴 차단.
  - `PostToolUse(Edit|Write)`: 자동 `ruff --fix` + `ruff check --select DTZ`(datetime naive 차단) + 변경 라인이 5파일 초과 시 경고.
  - `Stop`: pytest/mypy/ruff 미실행으로 종료하려 하면 차단, Verifier 단계 강제.
- **정적 안전망 강화**
  - `pyproject.toml` ruff 설정에 `DTZ` 룰셋과 `S`(보안), `B`(bugbear) 추가. naive datetime 재발 차단.
  - pre-commit 훅(로컬·CI 모두)에 동일 룰셋 적용.
- **복구 자동화**
  - 사이클 시작 시 `git stash` 자동 생성 → Verifier FAIL 시 `git restore + stash pop` 또는 `git reset --hard <last-tag>`.
  - `claude-progress.json`에 “마지막 안전 태그”를 항상 기록 → watchdog의 `auto_heal.sh`도 이 태그를 참조해 롤백.
  - `auto_heal.sh` 하루 1회 제한을 “사이클 기준 1회”로 완화, 단 동일 실패 사유 N회 연속 시 stop + Telegram 강한 알람.
- **제안서 상태 머신을 DB로 이전**
  - `proposals` 테이블 신설 (`id`, `path`, `title`, `category`, `state`, `priority`, `last_attempt_at`, `failure_reason`, `cycle_id`).
  - md 파일은 사람이 읽는 표현. 상태의 sole source of truth는 DB. MCP `update_status` 호출만이 상태를 바꾼다.
- **Default-FAIL contract 구현**
  - Verifier가 받아야 할 증거: 각 제안서당 ①pytest JSON 리포트(`--json-report`), ②mypy JSON 출력, ③ruff JSON 출력, ④변경 파일 diff. 네 가지가 모두 attach되지 않은 사이클은 자동 FAIL.

**기대 효과**: 동일 카테고리 버그(D7) 재발 사전 차단, 자동 롤백의 의도성·재현성 확보, 안전 규칙이 모델 정직성에 의존하지 않음.

---

### 축 C. 관측성·평가 하네스 — implementation_logs를 3축 observability로 확장

**해결 진단**: D2, D6, D7

**왜**: 지금은 “성공한 변경”만 DB에 적재되고, 실패한 시도, 실패 후 재시도 결과, 동일 영역 반복 수정 빈도 등이 추적되지 않는다. Agentic Harness Engineering이 정리한 component/experience/decision 3축은 “하네스를 진화시키기 위한 최소 데이터셋”이다.

**무엇을 한다**

- **Component Observability**
  - 자동 구현이 건드린 “하네스 컴포넌트”를 명시적으로 분류: 시스템 프롬프트 / Skill / Subagent 정의 / MCP 도구 / Hook / 코드(전략·API·DB).
  - `implementation_logs.changed_files`에 components 메타데이터를 같이 적재 (예: `{"path": "src/strategy/rsi.py", "component": "code/strategy", "lines_changed": 14}`).
- **Experience Observability**
  - 매 사이클의 trajectory를 JSONL로 보존: 단계(initializer/validator/implementer/verifier/recorder), 입력 요약, 결과, 소요 시간, 토큰 사용량.
  - 동일 영역 N회 수정·동일 사유 N회 실패를 자동 집계해 daily report에 “재발 위험 항목”으로 노출.
- **Decision Observability**
  - 각 제안서에 “예상 효과”를 정량 prediction으로 기록(예: `win_rate Δ +2%p`, `error_count Δ -30%`). 다음 주간 리포트에서 실측치와 자동 대조.
  - 예측 정확도가 낮은 카테고리/전략은 다음 사이클에서 우선순위 down-weight.
- **Eval Harness — 골든 회귀 셋**
  - 과거 implemented 제안서 중 “재발하면 안 되는 회귀”를 골라 `tests/eval/golden_proposals/` 디렉토리에 변경 전후 스냅샷으로 보존.
  - CI(또는 Phase 2 이후 사이클 시작 직전)에서 골든 셋 회귀 테스트 실행. 한 건이라도 실패하면 사이클 차단.
  - DeepEval/LangSmith 류 외부 의존은 도입하지 않고 pytest + JSON 비교로 시작 (의존성 추가 금지 정책 준수).
- **대시보드 신규 페이지** `dashboard/pages/pipeline.py`
  - 사이클별 success rate, mean cycles to revert, top failure reasons, component edit heatmap, prediction calibration plot.
  - Streamlit + 기존 `implementation_logs` + 신설 trajectory 테이블만 사용 (외부 의존 없음).
- **Telegram 결산 강화**
  - 평문 + 구조화된 카드(현재) → “오늘 적용된 변경 + 회귀 위험 N건 + 예측 미달 N건” 3섹션으로.

**기대 효과**: 하네스가 데이터로 자기 자신을 검증/개선할 수 있는 최소 토대 확보. “감으로 튜닝하던 자동 파이프라인”을 “계측된 시스템”으로 전환.

---

### 축 D. Claude Agent SDK / 하위 에이전트·Skills·MCP 활용 본격화

**해결 진단**: D1, D4, D8

**왜**: 축 A·B·C가 “구조와 데이터”를 다룬다면, 축 D는 그것을 **Claude Code 네이티브 메커니즘**으로 구현하는 방법이다. 따로 만들지 않고 이미 검증된 5계층 ADK를 채택하면 마이그레이션 비용이 낮고 커뮤니티 패턴 재사용이 쉽다.

**무엇을 한다**

- **`.claude/agents/`에 5종 서브에이전트 마크다운 선언**
  - `proposal-validator.md` — Read/Grep만 허용, kis-postgres MCP의 read-only 호출만 허용.
  - `implementer.md` — Read/Edit/Write/Bash 허용, `.env`/credentials는 Hook으로 차단.
  - `verifier.md` — Read/Bash(pytest/mypy/ruff)만, Edit/Write 절대 금지.
  - `evaluator.md` — fresh context, 골든 회귀 셋 결과만 채점.
  - `rollback-handler.md` — Bash(`git restore`, `git reset`) + Telegram MCP만.
- **`.claude/skills/`에 도메인 워크플로 분리**
  - `proposal-validation/SKILL.md` — BRIDGE_SPEC 안전 규칙·파라미터 범위·가중치 합계 검증 절차.
  - `kis-api-rate-limit-pattern/SKILL.md` — RateLimiter 사용 규칙, WS 상태 머신.
  - `strategy-add-pattern/SKILL.md` — 신규 전략 추가 시 체크리스트(레지스트리 등록, 셀렉터 갱신, 테스트 패턴).
  - `alembic-migration-flow/SKILL.md` — 마이그레이션 자동 생성/검토/적용 워크플로.
  - 트리거 기반 로딩이므로 always-on 컨텍스트가 줄어든다(D1 해소).
- **MCP 서버 신설**
  - 단일 “Pipeline MCP” 서버(로컬 stdio)로 `list_ready_proposals`, `mark_in_flight`, `mark_implemented`, `mark_failed`, `append_progress`, `last_safe_tag` 등 6~8개 도구만 노출.
  - `kis-postgres` MCP와 분리해 “파이프라인 도메인” 책임 경계를 만든다.
- **병렬화**
  - 독립 제안서(파일 경로 비교집합)는 Claude Code의 서브에이전트 병렬 실행(MapReduce 패턴)으로 처리. 의존 있는 제안서만 직렬.
  - 사이클 시작 시 Initializer가 “의존 그래프”를 만들어 `claude-progress.json`에 적재.
- **Plan Mode 활용**
  - 큰 카테고리(`refactor`/`feature`) 제안서는 plan mode로 먼저 계획 → Default-FAIL 기준 합의 후 implementer에 위임.
- **Background mode**
  - 30초 이상 걸리는 단계(전체 pytest, 골든 회귀 셋)는 백그라운드로 분리, 결과 도착 시 Verifier가 합산.

**기대 효과**: 자체 오케스트레이션 코드를 최소화하고 Claude Code 표준 매커니즘으로 정렬. 외부 기여자·미래의 SDK 업그레이드와의 호환성이 자연스럽게 따라온다.

---

### 축 E. 리포트 파이프라인의 하네스화 — 4-cadence(일/주/월/분기) 전 영역으로 확장

**해결 진단**: D9, D11, 그리고 D2(자기보고 검증)·D6(관측성)·D8(단일 프롬프트)의 리포트 영역 변형

**왜**: 자동 구현 사이클이 다음 사이클의 결정 근거로 리포트를 사용한다. 즉 **리포트는 자동 구현 파이프라인의 입력**이다. 입력 신뢰도가 낮으면 그 위에 어떤 안전 게이트를 쌓아도 의사결정 품질이 따라오지 않는다. 게다가 현재 cadence는 주간·월간 두 박자만 안정 운영되어 의사결정 시간 해상도가 비대칭이다. 본 축의 궁극 목표는 **네 cadence(일/주/월/분기) 전부를 동일 하네스로 회전**시켜, 각자의 시간 해상도에 맞는 ready 제안서를 안전 게이트를 사전 통과시킨 상태로 흘려보내는 것이다.

#### Cadence별 역할 분리

| Cadence | 트리거 시점 | 주된 결정 영역 | 데이터 창 | 생성될 제안서 카테고리(주 사용) |
|---------|------------|----------------|----------|----------------------------------|
| **일간 (daily)** | 평일 16:00 (장 종료 직후) | 핫픽스성 미세 조정, 사고 회복, 당일 회귀 위험 알림 | 당일 trades·signals·errors | `bug_fix`, `config`(경량 파라미터 미세 조정) |
| **주간 (weekly)** | 월요일 09:00 | 파라미터 튜닝, 전략 보정, 스크리닝 임계값 조정 | 직전 주 5거래일 | `param_tuning`, `enhancement` |
| **월간 (monthly)** | 매월 1영업일 09:00 | 전략 유효성 재평가, 카테고리 가중치, 골든 회귀 셋 보강 후보 | 직전 월 거래일 + 누적 prediction calibration | `refactor`, `enhancement`, 골든 셋 등록 후보 |
| **분기 (quarterly)** | 매분기 1영업일 09:00 | 포트폴리오·리스크 한도·아키텍처 방향성, BRIDGE_SPEC 범위 자체의 적정성 재평가 | 직전 분기 + 누적 component/decision observability | `refactor`, `feature`, 그리고 **자동 게이트 통과가 아닌 “사람 검토 권고” 태그가 붙은 구조 제안** |

**중요 원칙**: cadence가 길어질수록 제안서의 **자동 적용 범위는 좁아진다.** 일간/주간 제안서는 BRIDGE_SPEC 안전 게이트 사전 검증을 통과하면 자동 구현 사이클로 직행한다. 월간은 자동 적용 + 일부는 사람 검토 권고. 분기는 기본이 “사람 검토 권고”이고, 그중 안전 게이트 범위 안의 항목만 자동 구현으로 흐른다. 이는 “하네스가 자기 자신의 운영 정책을 단기간에 뒤집지 않도록” 막는 안전 장치다.

#### 공통 하네스 토폴로지 (네 cadence 모두 동일)

- **Initializer (리포트 사이클 진입점)**
  - `scripts/query_analytics.py`(`daily|weekly|range|risk`)를 호출해 raw JSON을 수집하고 `report-progress.json`에 적재.
  - 어제·지난주 리포트의 “예측한 효과” 항목과 오늘 query_analytics의 실측치를 짝지어 prediction calibration 데이터를 같이 만든다(축 C의 Decision Observability 입력).
- **Data Auditor (subagent, Read-only)**
  - raw JSON의 무결성 점검: 거래일 수와 trades 배열 길이가 합치하는지, `total_pnl`과 daily curve의 합이 일치하는지, signal_accuracy 분모가 0인 케이스, NULL/NaN 검출.
  - 한 건이라도 무결성 위반이면 리포트 사이클을 “stub 리포트”(원자료만 첨부 + 사람 알림)로 종료. **거짓 신호를 만들기보다 침묵하는 쪽이 안전하다**는 원칙.
- **Analyst (subagent, Write 허용)**
  - 검증된 JSON을 받아 BRIDGE_SPEC의 리포트 규격(일일/주간/월간 템플릿)에 맞춰 마크다운 작성. 단, **모든 수치는 “해당 키 = query_analytics 출력의 어떤 경로”인지 인용 주석을 달도록 강제**(예: `<!-- src: summary.total_profit_loss -->`).
- **Critic / Verifier (fresh-context subagent, Write/Edit 금지)**
  - Default-FAIL contract로 채점한다:
    1. 본문의 모든 수치가 raw JSON과 정확히 일치하는가 (Analyst가 단 인용 주석 자동 대조)
    2. “전략 평가”, “리스크 분석”, “개선 포인트” 등 결론 섹션이 본문의 수치를 근거로 하는가 (각 문장에 인용된 수치가 1개 이상)
    3. 이전 리포트의 “기대 효과” 예측이 실측치와 비교되어 있는가
    4. 회귀 위험(같은 모듈 N회 수정, 동일 사유 N회 실패)이 데이터에 존재하면 리포트에 해당 섹션이 들어가 있는가
- **Proposal Synthesizer (subagent)**
  - 리포트의 “개선 포인트” 섹션을 자동으로 `docs/proposals/YYYY-MM-DD_*.md` 여러 파일로 분리 작성하고 `proposals` 테이블에 `state=ready`로 INSERT.
  - BRIDGE_SPEC의 안전 게이트(파라미터 범위, 금지 영역, 5파일 제한)를 **synthesize 시점에 검증** — 자동 구현 사이클까지 가지 않고 여기서 미리 reject(=synth 거부 + critic 노트). 자동 구현 사이클의 `skipped` 발생률을 사전에 낮춘다.
- **Recorder**
  - 리포트 파일, 분리된 제안서들, Critic 채점 결과, prediction calibration 결과를 `report_runs` 테이블(신설)에 trajectory와 함께 기록.

**Claude Code 5계층 ADK 매핑(리포트 영역, 4 cadence 공통)**

- **Skills** (cadence별 분리)
  - `daily-report-template/SKILL.md`, `weekly-report-template/SKILL.md`, `monthly-report-template/SKILL.md`, **`quarterly-report-template/SKILL.md`(신설)** — BRIDGE_SPEC의 리포트 규격을 cadence별 작성 패턴으로 분리.
  - `report-numeric-citation/SKILL.md` — 모든 수치에 `<!-- src: ... -->` 주석을 다는 패턴 강제 (cadence 무관).
  - `proposal-synthesis-from-report/SKILL.md` — 리포트의 “개선 포인트”를 cadence별 카테고리 매트릭스에 따라 안전 게이트 준수 제안서로 분리하는 절차. **분기 cadence의 경우 “사람 검토 권고” 태그를 기본값으로 부여.**
- **MCP**
  - 축 D의 “Pipeline MCP”에 리포트 도구 추가: `fetch_analytics(cadence, period)`, `get_last_predictions(cadence, period)`, `write_report(cadence, path, content, calibration)`, `synthesize_proposals(report_path, cadence)`.
- **Subagents**
  - `report-data-auditor.md`, `report-analyst.md`, `report-critic.md`, `proposal-synthesizer.md` — cadence는 입력 파라미터로 처리하고 에이전트 정의는 공유(코드 중복 방지).
- **Hooks**
  - `PostToolUse(Write)` on `docs/reports/*` → 자동으로 `report-citation-check.py` 실행(주석 누락·숫자 불일치 차단).
  - `Stop` 훅 → Critic FAIL 시 publish(=Telegram 전송, CHANGELOG 갱신, 제안서 split) 단계로 진입 자체를 차단.

**BRIDGE_SPEC 갱신 필요 항목 (Phase 5에서 PR)**

- **분기 리포트 규격 신설** — 파일명 `docs/reports/YYYY-Q[1-4]_quarterly.md`, 섹션 템플릿(분기 누적 KPI, 카테고리·전략별 성과, 예측 정확도 분기 추세, 회귀 위험 누적 분석, 구조적 개선 권고).
- **리포트 cadence별 “자동 적용 카테고리 매트릭스”** — 일/주/월/분기 각각 어떤 카테고리까지 자동 적용 허용인지 명문화.
- **`query_analytics.py`에 `quarterly` 커맨드 추가** — 출력 JSON 스키마 본 계획서의 cadence 표와 일치하도록.

**트리거 통합 (4 cadence 모두 동일 패턴)**

- **스케줄**
  - 일간: `com.kis.dailyanalysis.plist`(평일 16:00) — Cowork 측 사이클 정상화 포함.
  - 주간: `com.kis.weeklyanalysis.plist`(월요일 09:00) — 현행 유지.
  - 월간: `com.kis.monthlyanalysis.plist`(매월 1영업일 09:00) — 현행 유지 또는 신설(현재 plist 부재 시).
  - 분기: **`com.kis.quarterlyanalysis.plist`(매분기 1영업일 09:00) 신설.**
- **수동 트리거**: 축 A의 표준 채널을 그대로 사용.
  - Telegram: `/run_report daily|weekly|monthly|quarterly [date]`, `/status_report`, `/pause_report`.
  - CLI: `scripts/trigger_report.sh --cadence {daily|weekly|monthly|quarterly} [--date YYYY-MM-DD]`.
  - 대시보드: cadence별 “지금 실행” 버튼.
- 리포트 사이클이 ready 제안서를 생성하면, 그날의 자동 구현 사이클(17:00)이 그 제안서를 자연스럽게 처리하는 흐름이 표준 파이프라인이 된다. 분기 리포트의 “사람 검토 권고” 태그가 붙은 제안서는 자동 구현 사이클이 `skipped (review_required)`로 처리하고 Telegram으로 알림.

**기대 효과**

- 리포트의 수치 정합성을 인간 검토 없이 강제 → 자동 구현 사이클의 입력 신뢰도 확보.
- “개선 포인트 → 제안서 분리” 수작업 제거, 동시에 안전 게이트 사전 검증으로 자동 구현의 `skipped` 발생률 감소.
- prediction calibration이 리포트마다 누적 → 축 C의 Decision Observability KPI(예측 정확도)가 자연 산출.
- 리포트 자체도 회귀 가능: 골든 리포트 셋(과거 안전 사례)을 보존해 “Critic이 항상 통과시키는 함정” 검출.

---

## 5. 단계적 로드맵

> **원칙**: 모든 Phase는 “기존 자동 구현이 멈추지 않으면서” 점진 도입. 각 Phase의 산출물은 별도 RFC 또는 BRIDGE_SPEC 개정안으로 분리 작성한다.

### Phase 0 — 측정 베이스라인 (1주)
- 최근 90일 사이클의 success rate, mean cycles to revert, 동일 영역 재수정 빈도, 카테고리별 토큰 사용량을 일회성 스크립트로 산출해 본 문서의 정량 KPI 기준선을 확정한다.
- ruff 룰셋(DTZ/S/B) 활성화 + pre-commit 적용. (단독으로도 ROI 높은 quick win)

### Phase 1 — 안전 게이트의 코드화 + 수동 트리거 (1~2주, 축 A·B)
- `.claude/settings.json`에 Hook(PreToolUse/PostToolUse/Stop) 구성.
- Initializer 에이전트의 환경 점검 항목 정의 + `claude-progress.json` 스키마 v1 확정.
- `proposals` DB 테이블 신설(상태 머신 이전). md ↔ DB 동기화 마이그레이션.
- **수동 트리거 최소 셋**: `scripts/trigger_implement.sh`, Telegram `/run_implement`·`/status_implement`·`/pause_implement`. 동시 실행·최소 인터벌·real 환경 가드 포함.

### Phase 2 — Verifier 분리와 Eval Harness 부트스트랩 (2~3주, 축 A·C 일부)
- Verifier 서브에이전트(`fresh context, Write/Edit 금지`) 분리.
- Default-FAIL contract: pytest/mypy/ruff JSON 아티팩트 강제.
- 골든 회귀 셋(tests/eval/golden_proposals) 초기 10건 선정 + CI 통합.

### Phase 3 — 5계층 ADK 완성 + 병렬화 (3~4주, 축 A·D)
- `.claude/agents/` 5종, `.claude/skills/` 4종, “Pipeline MCP” 서버 도입.
- 독립 제안서 병렬 구현 (서브에이전트 worker pool).
- `auto_implement_prompt.txt`를 에이전트별 짧은 시스템 프롬프트로 분해.
- 이벤트 트리거 옵션(MCP의 `state=ready` 인덱싱) 도입 — 기본 OFF, critical 우선순위만 ON.

### Phase 4 — 3축 Observability 완성 + 대시보드 (2~3주, 축 C)
- trajectory JSONL 적재, component metadata 컬럼 추가, decision prediction 기록.
- `dashboard/pages/pipeline.py` 추가, Telegram 결산 카드 개편.

### Phase 5 — 리포트 파이프라인 하네스화 (단계적 cadence 활성화, 6~8주, 축 E)

> **운영 안전을 위해 cadence를 한 번에 4개 켜지 않는다.** 현재 안정 운영 중인 주간을 기준으로 양옆을 단계적으로 확장한다.

- **Phase 5.0 — 공통 토폴로지 구축 (2주)**
  - `report_runs` 테이블 신설 + raw analytics JSON 스냅샷 보존.
  - Data Auditor/Analyst/Critic/Proposal Synthesizer 서브에이전트 도입, 수치 인용 주석 강제 훅 적용.
  - `report-numeric-citation`·`proposal-synthesis-from-report` Skill, Pipeline MCP의 리포트 도구.
- **Phase 5.1 — 주간 cadence를 하네스로 이전 (1주)**
  - 현재 잘 도는 주간을 가장 먼저 새 토폴로지로 옮긴다(리스크 최소).
  - 골든 주간 리포트 셋 3~5건 보존, Critic Default-FAIL contract 검증.
- **Phase 5.2 — 월간 cadence 이전 + 분기 리포트 규격 신설 (1~2주)**
  - 월간 cadence를 하네스로 이전.
  - BRIDGE_SPEC PR: 분기 리포트 규격, `quarterly-report-template` Skill, `query_analytics.py quarterly` 커맨드, 자동 적용 카테고리 매트릭스.
- **Phase 5.3 — 일간 cadence 정상화 + 활성화 (1~2주)**
  - 일간 Cowork 사이클을 새 토폴로지로 부팅. 첫 2주는 “관찰 모드” — 제안서 자동 split은 켜되 자동 구현 사이클에는 `state=draft`로 들어가 사람이 `ready`로 승급해야만 처리.
  - 관찰 모드 동안 골든 일간 리포트 셋 5건 이상 축적되면 자동 승급 모드로 전환.
- **Phase 5.4 — 분기 cadence 첫 사이클 + “사람 검토 권고” 태그 정착 (1~2주)**
  - 분기 cadence를 처음 회전시킨다. 분기는 운영 시작 후 최소 2분기(=6개월) 동안 자동 적용 카테고리를 BRIDGE_SPEC 안전 게이트의 약 70% 수준으로 보수적 운영, 이후 데이터로 범위 확대 여부 판단.
  - 분기 제안서 중 “사람 검토 권고” 항목은 자동 구현 사이클이 `skipped (review_required)` + Telegram 알림으로 처리하는 흐름 검증.

> **타임라인은 “이상적 페이스” 기준 8~12주.** 실 사이클에서는 다른 매매 기능 변경이 끼므로, 각 Phase 종료 시 회귀 골든 셋 통과를 게이트로 두고 다음 Phase로 진입한다.

---

## 6. 성공 지표 (Phase 0에서 베이스라인 확정 후 목표값 합의)

- **사이클 성공률** — `implemented / (implemented + failed + skipped)` 의 30일 이동평균.
- **MTTR(Mean Time To Revert)** — Verifier FAIL 발생부터 마지막 안전 태그 복귀까지의 분 단위.
- **재발률** — 같은 모듈을 7일 내 다시 수정한 비율.
- **예측 정확도** — Decision Observability 예측 대비 실측치의 평균 절대 오차.
- **컨텍스트 비용** — 사이클당 평균 토큰 사용량 (5계층 ADK 도입 후 감소가 기대 효과).
- **회귀 차단 건수** — Hooks·골든 셋·DTZ 룰이 차단한 위반/회귀 시도 카운트.
- **리포트 수치 정합성률** — Critic 통과한 리포트 / 전체 리포트 사이클 (축 E 도입 후 100% 목표).
- **리포트→제안서 자동 분리율** — Synthesizer가 자동 split한 제안서 / 전체 ready 제안서 (수작업 감소 측정).
- **수동 트리거 사용 패턴** — 채널별(Telegram/CLI/대시보드) 발동 빈도와 그 결과 사이클의 성공률.
- **Cadence 커버리지** — 4 cadence(일/주/월/분기) 중 Critic 통과 사이클이 안정 운영(=4주 연속 성공)되는 cadence 수. Phase 5 종료 시 4/4 목표.
- **Cadence별 제안서 자동 적용률** — 일/주/월/분기별 `implemented / (ready로 승급된 제안서 수)`. cadence가 길어질수록 낮아지는 것이 의도된 모습.
- **분기 리포트의 “사람 검토 권고” 비율** — 분기 리포트가 생성한 제안서 중 `review_required` 비중. 초기 70% 이상에서 시간에 따라 자연스러운 감소 추세 확인.

---

## 7. 비포함 항목 (의도적 제외)

- **외부 Eval 플랫폼 도입**(LangSmith, DeepEval, Phoenix 등) — Phase 4 종료 시점에 재검토. BRIDGE_SPEC의 “외부 의존 추가는 수동 검토” 정책을 따른다.
- **모델 자체 변경(예: Sonnet → Opus 사이클별 다중 모델 라우팅)** — 하네스 안정화 이후 별도 RFC.
- **실거래(KIS_ENV=real) 자동 전환** — 본 계획의 범위 밖. 안전 게이트의 절대 금지 영역 유지.
- **자체 Web UI로 자동 구현 제어** — Streamlit 대시보드 페이지로 충분, 별도 서버 미도입.

---

## 8. 참고 자료

- [Anthropic — Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic — Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic — Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [Anthropic — cwc-long-running-agents (GitHub)](https://github.com/anthropics/cwc-long-running-agents)
- [Anthropic — Claude Code Advanced Patterns: Subagents, MCP, and Scaling to Real Codebases](https://www.anthropic.com/webinars/claude-code-advanced-patterns)
- [Claude — Skills explained: How Skills compares to prompts, Projects, MCP, and subagents](https://claude.com/blog/skills-explained)
- [Martin Fowler — Harness engineering for coding agent users](https://martinfowler.com/articles/harness-engineering.html)
- [MongoDB — The Agent Harness: Why the LLM Is the Smallest Part of Your Agent System](https://www.mongodb.com/company/blog/technical/agent-harness-why-llm-is-smallest-part-of-your-agent-system)
- [Adnan Masood — Agent Harness Engineering: The Rise of the AI Control Plane](https://medium.com/@adnanmasood/agent-harness-engineering-the-rise-of-the-ai-control-plane-938ead884b1d)
- [arXiv 2604.25850 — Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses](https://arxiv.org/abs/2604.25850)
- [arXiv 2603.27355 — LLM Readiness Harness: Evaluation, Observability, and CI Gates for LLM/RAG Applications](https://arxiv.org/abs/2603.27355)
- [OpenHands SDK paper (arXiv 2511.03690)](https://arxiv.org/html/2511.03690v1)
- [HumanLayer — Skill Issue: Harness Engineering for Coding Agents](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)
- [AddyOsmani — Agent Harness Engineering](https://addyosmani.com/blog/agent-harness-engineering/)
- [awesome-harness-engineering (GitHub)](https://github.com/ai-boost/awesome-harness-engineering)
