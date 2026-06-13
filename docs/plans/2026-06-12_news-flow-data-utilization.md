# 작업계획 — 뉴스/수급 데이터 활용 (실전 환경)

- 작성일: 2026-06-12
- 작성: Cowork
- 상태: planned (자동 파이프라인 비대상 — `docs/proposals/` 아님, 수동 검토·구현)
- 우선순위: HIGH (선행 인프라) / MEDIUM (활용부)
- 담당: db-scheduler-engineer(`src/db/`, `src/worker/`), api-engineer(`src/worker/collectors/`), team lead(`src/engine.py` 배선)
- 연계: `docs/proposals/2026-06-12_flow-filter-shadow.md` (순수 스코어러 슬라이스 — 자동 구현)
- 선행 의존: 없음 (Phase 0부터 단독 실행 가능)

## 1. 배경 / 실측 (자기완결 — 컨텍스트 없이 읽어도 됨)

2026-06-12 실전 DB `news_chunks` 실측:

- **13건, ticker 1개**(005880, 유일 보유 종목), `source_type` **NEWS만**(DISCLOSURE/DART **0건**)
- **`sentiment`·`importance` 전부 NULL** (embedding은 13건 모두 채워짐)
- `event_time` 5/29~6/10, 매일 15:30(장마감) 1회, **2일 지연**(6/12에 6/10치)
- `news_collection_state` **비어 있음**
- 대조: 2026-05-21 모의 DB엔 714건(NEWS 582 / DISCLOSURE 132). → 실전 전환(6/8 `real` 시작, `DATABASE_URL_REAL`) 시 사실상 **리셋 + 실전 수집 미가동** 상태.

**해석**: 지금은 "활용"할 데이터가 사실상 없다. 수집 범위(보유 1종목)·소스(DART 미가동)·스코어링(NULL)이 모두 복구돼야 활용이 의미를 가진다. 데이터가 채워지기 전에 매매 신호로 쓰면, 이번 분석에서 반복 확인한 "없는 데이터 위에 빌드" 함정에 빠진다.

## 2. 현황 진단 포인트 (코드 확인됨 / 확인 필요)

- **스코어링은 수집 경로에 이미 wired** — `src/worker/collectors/base.py:205` `_build_new_chunks()`가 `get_scorer().score(...)`로 `sentiment`/`importance`를 채운다. 그런데 실전 13건은 NULL → 가설 (A) scorer가 수급(NEWS) 텍스트에 None 반환, 또는 (B) 이 행들이 스코어링 경로를 우회(`scripts/collect_market_stats.py` 등)해 적재. **Phase 0에서 확정.**
- **수급 숫자는 상류에 구조화 존재** — `src/market_stats.py`가 투자자별 매매/공매도를 포맷팅해 `chunk_text`로 만든다. 즉 파싱은 텍스트 표현을 되돌리는 작업이며, 장기적으로는 상류 구조화 값을 직접 쓰는 게 낫다.
- **DART collector 존재하나 실전 미가동 의심** — `src/worker/collectors/dart.py`는 있으나 실전 `news_collection_state`에 dart 항목 없음 → 실전 워커 collector 목록에 미등록/미가동 가능. **Phase 0 확인.**
- **수집 대상 ticker 결정 로직** — 실전에서 005880(보유 종목)만 적재되는 이유가 "보유 포지션 기준"인지 확인 필요. 활용의 핵심 전제(진입 *전* 후보 데이터)와 직결.

## 3. 목표 / 범위

- 실전 환경에서 뉴스/수급/공시가 **스크리닝 후보 단위로 신선하게 적재 + 점수화**되어, 매매 보조신호로 검증 가능한 상태.
- 범위: `src/worker/`, `src/db/`, `src/rag/scorer.py`, `src/engine.py`(배선 — 최소·shadow 우선). **전략 순수성 유지**(전략은 데이터를 인자로만 수신, DB/API 직접 호출 금지 — CLAUDE.md 모듈 경계).

## 4. 작업 단계

### Phase 0 — 진단 (수정 전 1회)
1. 실전 DB 13건의 **적재 경로 확정**(스코어 NULL 원인 A/B), DART state 부재 원인, 수급 collector의 ticker 범위 결정 로직.
2. 실전 워커(`com.kis.news-collector`)가 띄우는 collector 목록·가동 여부 로그 확인.
3. `git log -- src/worker/ src/rag/scorer.py`로 실전 전환 전후 변경 확인.

### Phase 1 — 수집 범위 확대 (보유 → 스크리닝 top-N)
- 수급/뉴스 수집 대상 ticker를 "보유 포지션"에서 **당일 스크리닝 상위 후보(`SCREENING_TOP_N`)**로 확대. 진입 *전* 데이터 확보가 목적(현재는 사후약방문).
- 부하: top-N × 일 1회면 호출 적음. 반드시 `src/api/rate_limiter.py` 경유.

### Phase 2 — 스코어링 가동 (sentiment/importance 채우기)
- 수급(NEWS) 텍스트에는 'sentiment'보다 **flow 부호/규모**가 적합 → scorer가 수급 source에 대해 `importance`=순매수 규모(거래대금 대비), `sentiment` 자리에 flow 방향을 채우도록 보정.
- 기존 NULL분은 `scripts/backfill_news_scores.py`를 실전 DB 대상 1회 실행.
- 외부 감정모델/패키지가 필요하면 **수동**(안전게이트: 패키지 추가 금지).

### Phase 3 — 매매 보조신호 배선 (shadow 우선)
- `src/strategy/flow_filter.py`(자동 제안서로 선반영되는 순수 스코어러)를 엔진에 연결:
  - 엔진이 후보별 최신 `news_chunks`(전일 수급)를 **read-only** 조회 → `parse_flow_text` → `flow_score`.
  - **우선 SHADOW**: 단독표 BUY(conf≥0.7) 발생 시 `flow_score`를 `signals.meta`/`SIGNAL_SKIP`에 **기록만**(매수 차단/허용은 변경하지 않음). 예측력 데이터 축적.
- 2일 지연 → **'전일 기준 오버나잇 필터'로만** 사용. 인트라데이 판단엔 부적합.

### Phase 4 — 보유 포지션 리스크 모니터
- 보유 종목의 **공매도 잔고 급증 / 기관·연기금 순매도 전환** 감지 → 텔레그램 경고(우선). 손절 타이트닝 연동은 **고위험 → 사용자 확인 게이트**.

### Phase 5 — 검증 후 게이트 활성화
- Phase 3 shadow 데이터로 **"flow_score 부호 → 익일 수익률" 상관**을 백테스트. 유의하면 단독표 BUY 확인 게이트로 승격(예: `flow_score<0`이면 단독 BUY 보류).
- 충분한 표본 전에는 **라이브 게이트 활성 금지**(원칙: 측정 먼저).

## 5. 수용 기준
- [ ] 실전 `news_chunks`가 스크리닝 후보 다종목 + 당일까지 적재
- [ ] `sentiment`/`importance`(또는 flow_score) 채워짐 (NULL 비율 < 5%)
- [ ] DART 공시 실전 수집 재개
- [ ] `flow_score` shadow 로깅 동작 + 예측력 백테스트 산출
- [ ] pytest/mypy/ruff 통과, 회귀 0

## 6. 주의 / 제약
- **안전게이트(BRIDGE_SPEC)**: 인프라(`worker`/`db`/`rag`)는 신규 파일이 `src/strategy`·`tests` 외 불가 + 스키마/패키지 변경 금지 → 자동 제안서 부적합. 그래서 본 계획은 수동(선례: `docs/plans/2026-05-21_news-collection-stall-fix.md`).
- **모듈 경계(CLAUDE.md)**: `src/db`=db-scheduler, `collectors`/`api`=api-engineer, `engine`/`notify`=team lead. 인터페이스 변경 시 합의.
- **단일 kis-postgres 공유** — 긴 트랜잭션/락 주의(2026-05-20 락 고갈 선례). 조회는 read-only·짧게.
- **전략 순수성**: flow 데이터 fetch는 engine/repo가 담당, 전략(`flow_filter`)은 인자로만 받는다.

## 7. 트리거 프롬프트 (이 파일을 시작점으로 새 세션에서 실행)
```
docs/plans/2026-06-12_news-flow-data-utilization.md 를 읽고 Phase 0(진단)부터 실행해줘.
실전 DB(news_chunks 13건·1종목·점수 NULL)의 적재 경로와 DART 미가동 원인을 확정한 뒤
Phase 1~2(수집범위 확대 + 스코어링 가동)를 TDD로 진행해. 매매경로 변경은 Phase 3에서
shadow 로깅부터. DB는 kis-postgres MCP(또는 docker exec kis-postgres psql)로 조회.
수정 후 pytest/ruff/mypy 통과 + scripts/record_implementation.py 기록 + CHANGELOG rolling
갱신 후 새 브랜치 커밋. 반영 확인용 워커 재시작이 필요하면 launchctl 명령을 나에게 제시해줘.
```
